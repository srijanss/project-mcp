import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from project_mcp.config import load_config
from tests.git_fixtures import build_git_fixture
from project_mcp.db import get_connection
from project_mcp.schema import CURRENT_SCHEMA_VERSION
from project_mcp.indexer import (
    begin_index,
    ensure_fresh_index,
    get_index_status,
    index_legacy_signals,
    mark_index_complete,
    refresh_index,
    remove_file,
    run_scan,
    upsert_file,
)
from project_mcp.plugins.python.analyzer import resolve_relative_imports
from project_mcp.plugins.python.linking import resolve_source_root_imports

FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "python" / "sample_project"
)


def _copy_fixture(tmp_path: Path) -> Path:
    project_root = tmp_path / "sample_project"
    shutil.copytree(FIXTURE_ROOT, project_root)
    return project_root


def test_begin_index_creates_project_row(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    conn = get_connection(tmp_path)

    project_id = begin_index(conn, tmp_path)

    row = conn.execute(
        "SELECT root_path FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    assert row == (str(tmp_path),)


def test_begin_index_is_idempotent_for_same_project_root(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    conn = get_connection(tmp_path)

    first_id = begin_index(conn, tmp_path)
    second_id = begin_index(conn, tmp_path)

    count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    assert first_id == second_id
    assert count == 1


def test_upsert_file_inserts_new_file_row(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    conn = get_connection(tmp_path)
    project_id = begin_index(conn, tmp_path)

    file_id = upsert_file(
        conn,
        project_id,
        "src/app.py",
        language="python",
        file_kind="source",
        size=123,
        mtime_ns=456,
        content_hash="abc123",
        parser_version="1",
    )

    row = conn.execute(
        "SELECT path, language, file_kind, size FROM files WHERE id = ?",
        (file_id,),
    ).fetchone()
    assert row == ("src/app.py", "python", "source", 123)


def test_upsert_file_updates_existing_row_on_same_path(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    conn = get_connection(tmp_path)
    project_id = begin_index(conn, tmp_path)

    first_id = upsert_file(conn, project_id, "src/app.py", size=100)
    second_id = upsert_file(conn, project_id, "src/app.py", size=200)

    count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    size = conn.execute(
        "SELECT size FROM files WHERE id = ?", (second_id,)
    ).fetchone()[0]
    assert first_id == second_id
    assert count == 1
    assert size == 200


def test_remove_file_deletes_file_and_cascades_symbols_and_tests(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    conn = get_connection(tmp_path)
    project_id = begin_index(conn, tmp_path)
    file_id = upsert_file(conn, project_id, "src/app.py")
    conn.execute(
        "INSERT INTO symbols (file_id, name, kind) VALUES (?, 'App', 'class')",
        (file_id,),
    )
    conn.execute(
        "INSERT INTO tests (file_id, test_kind) VALUES (?, 'unit')", (file_id,)
    )
    conn.commit()

    remove_file(conn, project_id, "src/app.py")

    files = conn.execute("SELECT * FROM files").fetchall()
    symbols = conn.execute("SELECT * FROM symbols").fetchall()
    tests = conn.execute("SELECT * FROM tests").fetchall()
    assert files == []
    assert symbols == []
    assert tests == []


def test_remove_file_deletes_relationships_referencing_file_or_its_symbols(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    conn = get_connection(tmp_path)
    project_id = begin_index(conn, tmp_path)
    file_id = upsert_file(conn, project_id, "src/app.py")
    other_file_id = upsert_file(conn, project_id, "src/other.py")
    conn.execute(
        "INSERT INTO symbols (file_id, name, kind) VALUES (?, 'App', 'class')",
        (file_id,),
    )
    symbol_id = conn.execute(
        "SELECT id FROM symbols WHERE file_id = ?", (file_id,)
    ).fetchone()[0]
    # relationship keyed on the file itself
    conn.execute(
        """
        INSERT INTO relationships
            (source_entity_type, source_entity_id, target_entity_type,
             target_entity_id, relationship_type)
        VALUES ('file', ?, 'file', ?, 'imports')
        """,
        (other_file_id, file_id),
    )
    # relationship keyed on a symbol owned by the removed file
    conn.execute(
        """
        INSERT INTO relationships
            (source_entity_type, source_entity_id, target_entity_type,
             target_entity_id, relationship_type)
        VALUES ('symbol', ?, 'symbol', 999, 'calls')
        """,
        (symbol_id,),
    )
    conn.commit()

    remove_file(conn, project_id, "src/app.py")

    relationships = conn.execute("SELECT * FROM relationships").fetchall()
    assert relationships == []


def test_get_index_status_before_any_index_run(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    conn = get_connection(tmp_path)

    status = get_index_status(conn)

    assert status["status"] == "never_indexed"


def test_begin_index_sets_status_indexing(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    conn = get_connection(tmp_path)

    begin_index(conn, tmp_path)

    assert get_index_status(conn)["status"] == "indexing"


def test_mark_index_complete_sets_status_fresh(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    conn = get_connection(tmp_path)
    begin_index(conn, tmp_path)

    mark_index_complete(conn)

    status = get_index_status(conn)
    assert status["status"] == "fresh"
    assert status["schema_version"] == CURRENT_SCHEMA_VERSION


def test_run_scan_persists_discovered_files_and_marks_fresh(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    paths = {
        row[0] for row in conn.execute("SELECT path FROM files").fetchall()
    }
    assert "app/models.py" in paths
    assert "tests/test_models.py" in paths
    assert not any(path.startswith(".venv/") for path in paths)
    assert not any(path.startswith("node_modules/") for path in paths)
    assert not any(path.startswith("target/") for path in paths)
    assert get_index_status(conn)["status"] == "fresh"


def test_run_scan_persists_python_dependencies(tmp_path):
    project_root = _copy_fixture(tmp_path)
    (project_root / "requirements.txt").write_text("requests>=2.31\n")
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    assert conn.execute(
        "SELECT name, ecosystem, declared_version, resolved_version FROM dependencies"
    ).fetchall() == [("requests", "python", ">=2.31", None)]


def test_python_fixture_indexes_declared_and_resolved_dependencies(tmp_path):
    project_root = _copy_fixture(tmp_path)
    (project_root / "pyproject.toml").write_text(
        '[project]\ndependencies = ["requests>=2"]\n'
    )
    (project_root / "requirements.txt").write_text("pytest>=8\n")
    (project_root / "uv.lock").write_text(
        '[[package]]\nname = "requests"\nversion = "2.32.3"\n'
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    assert conn.execute(
        "SELECT name, declared_version, resolved_version FROM dependencies ORDER BY name"
    ).fetchall() == [
        ("pytest", ">=8", None),
        ("requests", None, "2.32.3"),
    ]


def test_run_scan_persists_resolved_python_dependencies(tmp_path):
    project_root = _copy_fixture(tmp_path)
    (project_root / "pyproject.toml").write_text(
        '[project]\ndependencies = ["requests>=2"]\n'
    )
    (project_root / "uv.lock").write_text(
        '[[package]]\nname = "requests"\nversion = "2.32.3"\n'
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    assert conn.execute(
        "SELECT name, declared_version, resolved_version FROM dependencies"
    ).fetchall() == [("requests", None, "2.32.3")]


def test_run_scan_second_pass_skips_unchanged_files_but_reindexes_modified_ones(
    tmp_path,
):
    import time

    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)
    first_pass = dict(
        conn.execute("SELECT path, indexed_at FROM files").fetchall()
    )

    time.sleep(0.01)
    (project_root / "app" / "models.py").write_text(
        (project_root / "app" / "models.py").read_text() + "\n# touched\n"
    )

    run_scan(conn, project_root, config)
    second_pass = dict(
        conn.execute("SELECT path, indexed_at FROM files").fetchall()
    )

    assert second_pass["app/models.py"] != first_pass["app/models.py"]
    assert second_pass["tests/test_models.py"] == first_pass["tests/test_models.py"]
    assert second_pass["README.md"] == first_pass["README.md"]


def test_run_scan_does_not_requery_existing_paths_redundantly(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    file_queries = []
    conn.set_trace_callback(
        lambda sql: file_queries.append(sql)
        if "FROM files WHERE project_id" in sql
        else None
    )

    run_scan(conn, project_root, config)
    conn.set_trace_callback(None)

    # Two queries: one for file discovery, one for framework enrichment
    assert len(file_queries) <= 2


def test_run_scan_persists_python_symbols_for_discovered_files(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    qualified_names = {
        row[0] for row in conn.execute("SELECT qualified_name FROM symbols").fetchall()
    }

    assert "app.models" in qualified_names
    assert "app.models.Widget" in qualified_names
    assert "app.models.Widget.__init__" in qualified_names


def test_run_scan_persists_js_symbols_for_discovered_files(tmp_path):
    project_root = tmp_path / "js_project"
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "widget.js").write_text(
        "function topLevel(x) {\n  return x;\n}\n\nclass Widget {\n  render() {\n    return 1;\n  }\n}\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    rows = {
        row[0]: row[1]
        for row in conn.execute("SELECT qualified_name, language FROM symbols").fetchall()
    }

    assert rows.get("app.widget.topLevel") == "javascript"
    assert rows.get("app.widget.Widget") == "javascript"


def test_run_scan_persists_js_import_relationship_for_resolvable_relative_import(tmp_path):
    project_root = tmp_path / "js_project"
    (project_root / "src").mkdir(parents=True)
    (project_root / "src" / "App.js").write_text(
        "import Button from './Button';\n"
    )
    (project_root / "src" / "Button.js").write_text(
        "export default function Button() {\n  return null;\n}\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    source_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'src/App.js'"
    ).fetchone()[0]
    target_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'src/Button.js'"
    ).fetchone()[0]

    relationship = conn.execute(
        """
        SELECT relationship_type, confidence FROM relationships
        WHERE source_entity_type = 'file' AND source_entity_id = ?
          AND target_entity_type = 'file' AND target_entity_id = ?
        """,
        (source_file_id, target_file_id),
    ).fetchone()

    assert relationship == ("imports", "high")


def test_run_scan_does_not_persist_js_import_relationship_for_dynamic_import(tmp_path):
    project_root = tmp_path / "js_project"
    (project_root / "src").mkdir(parents=True)
    (project_root / "src" / "App.js").write_text(
        "const Button = await import('./Button');\n"
    )
    (project_root / "src" / "Button.js").write_text(
        "export default function Button() {\n  return null;\n}\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    source_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'src/App.js'"
    ).fetchone()[0]

    relationships = conn.execute(
        "SELECT * FROM relationships WHERE source_entity_type = 'file' AND source_entity_id = ?",
        (source_file_id,),
    ).fetchall()

    assert relationships == []


def test_refresh_index_resolves_js_import_once_target_file_is_added(tmp_path):
    project_root = tmp_path / "js_project"
    (project_root / "src").mkdir(parents=True)
    (project_root / "src" / "App.js").write_text(
        "import Button from './Button';\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    (project_root / "src" / "Button.js").write_text(
        "export default function Button() {\n  return null;\n}\n"
    )
    refresh_index(conn, project_root, config)

    source_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'src/App.js'"
    ).fetchone()[0]
    target_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'src/Button.js'"
    ).fetchone()[0]

    relationship = conn.execute(
        """
        SELECT relationship_type, confidence FROM relationships
        WHERE source_entity_type = 'file' AND source_entity_id = ?
          AND target_entity_type = 'file' AND target_entity_id = ?
        """,
        (source_file_id, target_file_id),
    ).fetchone()

    assert relationship == ("imports", "high")


def test_run_scan_does_not_persist_js_self_import_relationship(tmp_path):
    project_root = tmp_path / "js_project"
    (project_root / "src").mkdir(parents=True)
    (project_root / "src" / "Button.js").write_text(
        "import './Button';\n\nexport default function Button() {\n  return null;\n}\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'src/Button.js'"
    ).fetchone()[0]

    relationships = conn.execute(
        "SELECT * FROM relationships WHERE source_entity_type = 'file' AND source_entity_id = ?",
        (file_id,),
    ).fetchall()

    assert relationships == []


def test_run_scan_persists_js_import_relationship_for_multi_level_relative_import(tmp_path):
    project_root = tmp_path / "js_project"
    (project_root / "src" / "components").mkdir(parents=True)
    (project_root / "shared").mkdir(parents=True)
    (project_root / "src" / "components" / "App.js").write_text(
        "import { helper } from '../../shared/utils';\n"
    )
    (project_root / "shared" / "utils.js").write_text(
        "export function helper() {\n  return 1;\n}\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    source_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'src/components/App.js'"
    ).fetchone()[0]
    target_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'shared/utils.js'"
    ).fetchone()[0]

    relationship = conn.execute(
        """
        SELECT relationship_type, confidence FROM relationships
        WHERE source_entity_type = 'file' AND source_entity_id = ?
          AND target_entity_type = 'file' AND target_entity_id = ?
        """,
        (source_file_id, target_file_id),
    ).fetchone()

    assert relationship == ("imports", "high")


def test_refresh_index_persists_js_symbols_for_newly_added_file(tmp_path):
    project_root = tmp_path / "js_project"
    project_root.mkdir(parents=True)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    (project_root / "widget.js").write_text(
        "function topLevel(x) {\n  return x;\n}\n"
    )
    refresh_index(conn, project_root, config)

    rows = {
        row[0]: row[1]
        for row in conn.execute("SELECT qualified_name, language FROM symbols").fetchall()
    }

    assert rows.get("widget.topLevel") == "javascript"


def test_run_scan_persists_rust_symbols_for_discovered_files(tmp_path):
    project_root = tmp_path / "rust_project"
    (project_root / "src").mkdir(parents=True)
    (project_root / "src" / "widget.rs").write_text(
        "struct Widget {\n    name: String,\n}\n\nfn render() -> String {\n    String::new()\n}\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    rows = {
        row[0]: row[1]
        for row in conn.execute("SELECT qualified_name, language FROM symbols").fetchall()
    }

    assert rows.get("src.widget.Widget") == "rust"
    assert rows.get("src.widget.render") == "rust"


def test_refresh_index_persists_rust_symbols_for_newly_added_file(tmp_path):
    project_root = tmp_path / "rust_project"
    project_root.mkdir(parents=True)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    (project_root / "widget.rs").write_text("fn render() -> String {\n    String::new()\n}\n")
    refresh_index(conn, project_root, config)

    rows = {
        row[0]: row[1]
        for row in conn.execute("SELECT qualified_name, language FROM symbols").fetchall()
    }

    assert rows.get("widget.render") == "rust"


def test_run_scan_persists_rust_dependencies(tmp_path):
    project_root = tmp_path / "rust_project"
    project_root.mkdir(parents=True)
    (project_root / "Cargo.toml").write_text(
        '[package]\nname = "widget"\nversion = "0.1.0"\n\n[dependencies]\nserde = "1.0"\n'
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    assert conn.execute(
        "SELECT name, ecosystem, declared_version, resolved_version FROM dependencies"
    ).fetchall() == [("serde", "rust", "1.0", None)]


def test_run_scan_persists_npm_dependencies(tmp_path):
    project_root = tmp_path / "npm_project"
    project_root.mkdir(parents=True)
    (project_root / "package.json").write_text(
        '{"name": "widget", "dependencies": {"left-pad": "^1.3.0"}}'
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    assert conn.execute(
        "SELECT name, ecosystem, declared_version, resolved_version FROM dependencies"
    ).fetchall() == [("left-pad", "npm", "^1.3.0", None)]


def test_run_scan_persists_resolved_npm_dependencies(tmp_path):
    project_root = tmp_path / "npm_project"
    project_root.mkdir(parents=True)
    (project_root / "package.json").write_text(
        '{"name": "widget", "dependencies": {"left-pad": "^1.3.0"}}'
    )
    (project_root / "package-lock.json").write_text(
        """{
  "packages": {
    "": {"name": "widget"},
    "node_modules/left-pad": {"version": "1.3.0"}
  }
}
"""
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    assert conn.execute(
        "SELECT name, ecosystem, declared_version, resolved_version FROM dependencies"
    ).fetchall() == [("left-pad", "npm", None, "1.3.0")]


def test_run_scan_persists_rust_use_relationship_for_resolvable_crate_module(tmp_path):
    project_root = tmp_path / "rust_project"
    (project_root / "src").mkdir(parents=True)
    (project_root / "src" / "lib.rs").write_text(
        "use crate::widget::Widget;\n"
    )
    (project_root / "src" / "widget.rs").write_text(
        "pub struct Widget {\n    name: String,\n}\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    source_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'src/lib.rs'"
    ).fetchone()[0]
    target_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'src/widget.rs'"
    ).fetchone()[0]

    relationship = conn.execute(
        """
        SELECT relationship_type, confidence FROM relationships
        WHERE source_entity_type = 'file' AND source_entity_id = ?
          AND target_entity_type = 'file' AND target_entity_id = ?
        """,
        (source_file_id, target_file_id),
    ).fetchone()

    assert relationship == ("imports", "high")


def test_run_scan_persists_rust_use_relationship_for_nested_crate_module(tmp_path):
    project_root = tmp_path / "rust_project"
    (project_root / "src" / "foo").mkdir(parents=True)
    (project_root / "src" / "lib.rs").write_text(
        "use crate::foo::bar::Bar;\n"
    )
    (project_root / "src" / "foo" / "bar.rs").write_text(
        "pub struct Bar {\n    name: String,\n}\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    source_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'src/lib.rs'"
    ).fetchone()[0]
    target_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'src/foo/bar.rs'"
    ).fetchone()[0]

    relationship = conn.execute(
        """
        SELECT relationship_type, confidence FROM relationships
        WHERE source_entity_type = 'file' AND source_entity_id = ?
          AND target_entity_type = 'file' AND target_entity_id = ?
        """,
        (source_file_id, target_file_id),
    ).fetchone()

    assert relationship == ("imports", "high")


def test_run_scan_does_not_persist_rust_use_relationship_when_file_has_no_src_segment(tmp_path):
    project_root = tmp_path / "rust_project"
    project_root.mkdir(parents=True)
    (project_root / "lib.rs").write_text(
        "use crate::widget::Widget;\n"
    )
    (project_root / "widget.rs").write_text(
        "pub struct Widget {\n    name: String,\n}\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    source_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'lib.rs'"
    ).fetchone()[0]

    relationships = conn.execute(
        "SELECT * FROM relationships WHERE source_entity_type = 'file' AND source_entity_id = ?",
        (source_file_id,),
    ).fetchall()

    assert relationships == []


def test_run_scan_does_not_persist_rust_use_relationship_for_external_or_relative_module_paths(tmp_path):
    project_root = tmp_path / "rust_project"
    (project_root / "src").mkdir(parents=True)
    (project_root / "src" / "lib.rs").write_text(
        "use std::collections::HashMap;\n"
        "use self::widget::Widget;\n"
        "use super::other::Thing;\n"
    )
    (project_root / "src" / "widget.rs").write_text(
        "pub struct Widget {\n    name: String,\n}\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    source_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'src/lib.rs'"
    ).fetchone()[0]

    relationships = conn.execute(
        "SELECT * FROM relationships WHERE source_entity_type = 'file' AND source_entity_id = ?",
        (source_file_id,),
    ).fetchall()

    assert relationships == []


def test_run_scan_persists_trait_implementation_relationship_for_same_file_impl(tmp_path):
    project_root = tmp_path / "rust_project"
    (project_root / "src").mkdir(parents=True)
    (project_root / "src" / "widget.rs").write_text(
        "trait Greet {\n"
        "    fn greet(&self) -> String;\n"
        "}\n"
        "\n"
        "struct Widget {\n"
        "    name: String,\n"
        "}\n"
        "\n"
        "impl Greet for Widget {\n"
        "    fn greet(&self) -> String {\n"
        "        self.name.clone()\n"
        "    }\n"
        "}\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    trait_symbol_id = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'src.widget.Greet'"
    ).fetchone()[0]
    struct_symbol_id = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'src.widget.Widget'"
    ).fetchone()[0]

    relationship = conn.execute(
        """
        SELECT relationship_type, confidence FROM relationships
        WHERE source_entity_type = 'symbol' AND source_entity_id = ?
          AND target_entity_type = 'symbol' AND target_entity_id = ?
        """,
        (struct_symbol_id, trait_symbol_id),
    ).fetchone()

    assert relationship == ("implements", "high")


def test_run_scan_replaces_stale_symbols_when_python_file_changes(tmp_path):
    import time

    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    time.sleep(0.01)
    (project_root / "app" / "models.py").write_text(
        "class Widget:\n"
        "    def __init__(self, name: str):\n"
        "        self.name = name\n"
        "\n"
        "    def rename(self, name: str):\n"
        "        self.name = name\n"
    )

    run_scan(conn, project_root, config)

    qualified_names = {
        row[0] for row in conn.execute("SELECT qualified_name FROM symbols").fetchall()
    }

    assert "app.models.Widget.rename" in qualified_names
    assert len(
        [name for name in qualified_names if name == "app.models.Widget.__init__"]
    ) == 1


def test_run_scan_persists_import_relationship_for_resolvable_project_import(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    source_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'tests/test_models.py'"
    ).fetchone()[0]
    target_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'app/models.py'"
    ).fetchone()[0]

    relationship = conn.execute(
        """
        SELECT relationship_type, confidence FROM relationships
        WHERE source_entity_type = 'file' AND source_entity_id = ?
          AND target_entity_type = 'file' AND target_entity_id = ?
        """,
        (source_file_id, target_file_id),
    ).fetchone()

    assert relationship == ("imports", "high")


def test_run_scan_persists_test_relationship_for_resolvable_source_module(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    source_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'tests/test_models.py'"
    ).fetchone()[0]
    target_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'app/models.py'"
    ).fetchone()[0]

    relationship = conn.execute(
        """
        SELECT relationship_type, confidence, evidence_json FROM relationships
        WHERE source_entity_type = 'file' AND source_entity_id = ?
          AND target_entity_type = 'file' AND target_entity_id = ?
          AND relationship_type = 'tests'
        """,
        (source_file_id, target_file_id),
    ).fetchone()

    assert relationship[0] == "tests"
    assert relationship[1] == "high"
    assert json.loads(relationship[2]) == ["direct_import"]


def test_run_scan_persists_inheritance_relationship_for_same_file_base(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    (project_root / "app" / "shapes.py").write_text(
        "class Shape:\n"
        "    pass\n"
        "\n"
        "\n"
        "class Circle(Shape):\n"
        "    pass\n"
    )

    run_scan(conn, project_root, config)

    base_symbol_id = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'app.shapes.Shape'"
    ).fetchone()[0]
    class_symbol_id = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'app.shapes.Circle'"
    ).fetchone()[0]

    relationship = conn.execute(
        """
        SELECT relationship_type, confidence FROM relationships
        WHERE source_entity_type = 'symbol' AND source_entity_id = ?
          AND target_entity_type = 'symbol' AND target_entity_id = ?
        """,
        (class_symbol_id, base_symbol_id),
    ).fetchone()

    assert relationship == ("inherits", "high")


def test_run_scan_removes_inheritance_relationships_for_replaced_symbols(tmp_path):
    import time

    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    shapes_path = project_root / "app" / "shapes.py"
    shapes_path.write_text(
        "class Shape:\n"
        "    pass\n"
        "\n"
        "\n"
        "class Circle(Shape):\n"
        "    pass\n"
    )

    run_scan(conn, project_root, config)

    time.sleep(0.01)
    shapes_path.write_text("class Shape:\n    pass\n")
    run_scan(conn, project_root, config)

    relationships = conn.execute(
        "SELECT * FROM relationships WHERE relationship_type = 'inherits'"
    ).fetchall()

    assert relationships == []


def test_run_scan_refreshes_unchanged_importer_when_target_file_is_added(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    importer_path = project_root / "app" / "importer.py"
    importer_path.write_text("import app.later\n")

    run_scan(conn, project_root, config)
    source_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'app/importer.py'"
    ).fetchone()[0]
    assert conn.execute(
        """
        SELECT COUNT(*) FROM relationships
        WHERE relationship_type = 'imports'
          AND source_entity_type = 'file' AND source_entity_id = ?
        """,
        (source_file_id,),
    ).fetchone()[0] == 0

    (project_root / "app" / "later.py").write_text("VALUE = 1\n")
    run_scan(conn, project_root, config)

    target_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'app/later.py'"
    ).fetchone()[0]
    relationship = conn.execute(
        """
        SELECT relationship_type, confidence FROM relationships
        WHERE source_entity_type = 'file' AND source_entity_id = ?
          AND target_entity_type = 'file' AND target_entity_id = ?
        """,
        (source_file_id, target_file_id),
    ).fetchone()

    assert relationship == ("imports", "high")


def test_run_scan_does_not_reparse_unchanged_python_files_for_import_relationships(
    tmp_path, monkeypatch
):
    import project_mcp.plugins.python.analyzer as analyzer_module
    import project_mcp.plugins.python.linking as linking_module

    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    calls = []
    original_analyze = linking_module.analyze_python_source

    def spy(path, source):
        calls.append(path)
        return original_analyze(path, source)

    monkeypatch.setattr(analyzer_module, "analyze_python_source", spy)
    monkeypatch.setattr(linking_module, "analyze_python_source", spy)

    run_scan(conn, project_root, config)

    assert calls == []


def test_run_scan_parses_each_non_test_python_file_once(tmp_path, monkeypatch):
    import ast
    from collections import Counter

    project_root = _copy_fixture(tmp_path)
    (project_root / "app" / "helpers.py").write_text(
        "LIMIT = 1\n\n\ndef helper():\n    return LIMIT\n"
    )
    (project_root / "app" / "service.py").write_text(
        "from .helpers import helper\n\n\ndef run():\n    return helper()\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)
    parsed = Counter()
    original_parse = ast.parse

    def counting_parse(source, filename="<unknown>", *args, **kwargs):
        parsed[filename] += 1
        return original_parse(source, filename, *args, **kwargs)

    monkeypatch.setattr(ast, "parse", counting_parse)

    run_scan(conn, project_root, config)
    first_scan = {path: n for path, n in parsed.items() if "test" not in path}
    parsed.clear()
    (project_root / "app" / "helpers.py").write_text(
        "LIMIT = 2\n\n\ndef helper():\n    return LIMIT\n"
    )
    refresh_index(conn, project_root, config)
    refreshed = {path: n for path, n in parsed.items() if "test" not in path}

    assert first_scan["app/service.py"] == 1
    assert set(first_scan.values()) == {1}
    # The unchanged importer is re-linked to the edited file, parsed once too.
    assert refreshed == {"app/helpers.py": 1, "app/service.py": 1}


def test_run_scan_resolves_from_package_submodule_import(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "importer.py").write_text("from app import later\n")
    (project_root / "app" / "later.py").write_text("VALUE = 1\n")

    run_scan(conn, project_root, config)

    source_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'app/importer.py'"
    ).fetchone()[0]
    target_file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'app/later.py'"
    ).fetchone()[0]
    relationship = conn.execute(
        """
        SELECT relationship_type, confidence FROM relationships
        WHERE source_entity_type = 'file' AND source_entity_id = ?
          AND target_entity_type = 'file' AND target_entity_id = ?
        """,
        (source_file_id, target_file_id),
    ).fetchone()

    assert relationship == ("imports", "high")


def test_run_scan_persists_static_call_relationship_for_same_module_functions(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "workflow.py").write_text(
        "def helper():\n"
        "    return 'done'\n"
        "\n"
        "\n"
        "def run():\n"
        "    return helper()\n"
    )

    run_scan(conn, project_root, config)

    caller_id = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'app.workflow.run'"
    ).fetchone()[0]
    callee_id = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'app.workflow.helper'"
    ).fetchone()[0]
    relationship = conn.execute(
        """
        SELECT relationship_type, confidence FROM relationships
        WHERE source_entity_type = 'symbol' AND source_entity_id = ?
          AND target_entity_type = 'symbol' AND target_entity_id = ?
        """,
        (caller_id, callee_id),
    ).fetchone()

    assert relationship == ("calls", "high")


def test_run_scan_records_one_call_edge_per_caller_and_callee(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "workflow.py").write_text(
        "def helper():\n"
        "    return 'done'\n"
        "\n"
        "\n"
        "def run():\n"
        "    helper()\n"
        "    helper()\n"
        "    return helper()\n"
    )

    run_scan(conn, project_root, config)

    count = conn.execute(
        """
        SELECT COUNT(*) FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'calls'
          AND s.qualified_name = 'app.workflow.run'
          AND t.qualified_name = 'app.workflow.helper'
        """
    ).fetchone()[0]

    assert count == 1


def test_run_scan_persists_references_relationship_from_method_to_self_field(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "payment.py").write_text(
        "class Payment:\n"
        "    status = 'new'\n"
        "\n"
        "    def run(self):\n"
        "        return self.status\n"
    )

    run_scan(conn, project_root, config)

    method_id = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'app.payment.Payment.run'"
    ).fetchone()[0]
    field_id = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'app.payment.Payment.status'"
    ).fetchone()[0]
    relationship = conn.execute(
        """
        SELECT relationship_type, confidence FROM relationships
        WHERE source_entity_type = 'symbol' AND source_entity_id = ?
          AND target_entity_type = 'symbol' AND target_entity_id = ?
        """,
        (method_id, field_id),
    ).fetchone()

    assert relationship == ("references", "high")


def test_run_scan_persists_one_references_relationship_for_repeated_self_accesses(
    tmp_path,
):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "payment.py").write_text(
        "class Payment:\n"
        "    status = 'new'\n"
        "\n"
        "    def run(self):\n"
        "        if self.status == 'new':\n"
        "            self.status = 'done'\n"
        "        return self.status\n"
    )

    run_scan(conn, project_root, config)

    count = conn.execute(
        """
        SELECT COUNT(*) FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'references'
          AND s.qualified_name = 'app.payment.Payment.run'
          AND t.qualified_name = 'app.payment.Payment.status'
        """
    ).fetchone()[0]

    assert count == 1


def test_run_scan_persists_call_relationship_across_modules_via_from_import(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "helpers.py").write_text(
        "def helper():\n"
        "    return 1\n"
    )
    (project_root / "app" / "service.py").write_text(
        "from app.helpers import helper\n"
        "\n"
        "\n"
        "def run():\n"
        "    return helper()\n"
    )

    run_scan(conn, project_root, config)

    relationship = conn.execute(
        """
        SELECT r.relationship_type, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND s.qualified_name = 'app.service.run'
          AND t.qualified_name = 'app.helpers.helper'
        """
    ).fetchone()

    assert relationship == ("calls", "high")


def test_run_scan_resolves_calls_through_imported_module_attributes(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "helpers.py").write_text(
        "def helper():\n"
        "    return 1\n"
    )
    (project_root / "app" / "service.py").write_text(
        "import app.helpers\n"
        "import app.helpers as h\n"
        "from app import helpers\n"
        "\n"
        "\n"
        "def by_dotted_path():\n"
        "    return app.helpers.helper()\n"
        "\n"
        "\n"
        "def by_module_alias():\n"
        "    return h.helper()\n"
        "\n"
        "\n"
        "def by_from_imported_module():\n"
        "    return helpers.helper()\n"
        "\n"
        "\n"
        "def by_unknown_object(thing):\n"
        "    return thing.helper()\n"
    )

    run_scan(conn, project_root, config)

    callers = conn.execute(
        """
        SELECT s.qualified_name, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'calls'
          AND r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND t.qualified_name = 'app.helpers.helper'
        ORDER BY s.qualified_name
        """
    ).fetchall()

    assert callers == [
        ("app.service.by_dotted_path", "high"),
        ("app.service.by_from_imported_module", "high"),
        ("app.service.by_module_alias", "high"),
    ]


def test_run_scan_resolves_aliased_from_imports_for_calls_and_constants(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "helpers.py").write_text(
        "MAX_RETRIES = 3\n"
        "\n"
        "\n"
        "def helper():\n"
        "    return 1\n"
    )
    (project_root / "app" / "service.py").write_text(
        "from app.helpers import helper as do_help, MAX_RETRIES as RETRIES\n"
        "\n"
        "\n"
        "def run():\n"
        "    return do_help(), RETRIES\n"
    )

    run_scan(conn, project_root, config)

    edges = conn.execute(
        """
        SELECT t.qualified_name, r.relationship_type, r.confidence
        FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND s.qualified_name = 'app.service.run'
        ORDER BY t.qualified_name
        """
    ).fetchall()

    assert edges == [
        ("app.helpers.MAX_RETRIES", "references", "high"),
        ("app.helpers.helper", "calls", "high"),
    ]


def test_run_scan_persists_low_confidence_reference_to_field_in_imported_module(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "payments.py").write_text(
        "class Payment:\n"
        "    gateway_captured_card_number = None\n"
    )
    (project_root / "app" / "receipts.py").write_text(
        "from app.payments import Payment\n"
        "\n"
        "\n"
        "def show(payment):\n"
        "    return payment.gateway_captured_card_number\n"
    )

    run_scan(conn, project_root, config)

    relationship = conn.execute(
        """
        SELECT r.relationship_type, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND s.qualified_name = 'app.receipts.show'
          AND t.qualified_name = 'app.payments.Payment.gateway_captured_card_number'
        """
    ).fetchone()

    assert relationship == ("references", "low")


def test_run_scan_skips_attribute_reference_when_field_name_is_ambiguous(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "payments.py").write_text(
        "class Payment:\n    status = None\n"
    )
    (project_root / "app" / "orders.py").write_text(
        "class Order:\n    status = None\n"
    )
    (project_root / "app" / "receipts.py").write_text(
        "from app.payments import Payment\n"
        "from app.orders import Order\n"
        "\n"
        "\n"
        "def show(thing):\n"
        "    return thing.status\n"
    )

    run_scan(conn, project_root, config)

    count = conn.execute(
        """
        SELECT COUNT(*) FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        WHERE r.relationship_type = 'references'
          AND s.qualified_name = 'app.receipts.show'
        """
    ).fetchone()[0]

    assert count == 0


def test_run_scan_skips_attribute_reference_to_field_in_module_not_imported(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "payments.py").write_text(
        "class Payment:\n    gateway_captured_card_number = None\n"
    )
    (project_root / "app" / "receipts.py").write_text(
        "def show(payment):\n"
        "    return payment.gateway_captured_card_number\n"
    )

    run_scan(conn, project_root, config)

    count = conn.execute(
        """
        SELECT COUNT(*) FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        WHERE r.relationship_type = 'references'
          AND s.qualified_name = 'app.receipts.show'
        """
    ).fetchone()[0]

    assert count == 0


def _reference_confidence(conn, source_name: str, target_name: str):
    return conn.execute(
        """
        SELECT r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'references'
          AND r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND s.qualified_name = ? AND t.qualified_name = ?
        """,
        (source_name, target_name),
    ).fetchall()


def test_run_scan_persists_references_to_module_constants(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "settings.py").write_text(
        "MAX_RETRIES = 3\n"
        "\n"
        "\n"
        "def limit():\n"
        "    return MAX_RETRIES\n"
    )
    (project_root / "app" / "worker.py").write_text(
        "from app.settings import MAX_RETRIES\n"
        "\n"
        "\n"
        "class Card:\n"
        "    number = None\n"
        "\n"
        "\n"
        "def run(card):\n"
        "    return MAX_RETRIES, card.number\n"
    )
    (project_root / "app" / "receipts.py").write_text(
        "from app.worker import Card\n"
        "\n"
        "\n"
        "def show(card):\n"
        "    return card.number\n"
    )

    run_scan(conn, project_root, config)

    constant = "app.settings.MAX_RETRIES"
    assert _reference_confidence(conn, "app.settings.limit", constant) == [("high",)]
    assert _reference_confidence(conn, "app.worker.run", constant) == [("high",)]
    assert _reference_confidence(
        conn, "app.receipts.show", "app.worker.Card.number"
    ) == [("low",)]


def test_resolve_relative_imports_rewrites_them_as_absolute_modules():
    imports = [
        {"module": "os", "names": [], "level": 0, "line": 1},
        {"module": "helpers", "names": ["helper"], "level": 1, "line": 2,
         "aliases": {"h": "helper"}},
        {"module": None, "names": ["utils"], "level": 1, "line": 3},
        {"module": "shared", "names": ["X"], "level": 2, "line": 4},
        {"module": None, "names": ["deep"], "level": 4, "line": 5},
    ]

    assert resolve_relative_imports("app/jobs/nightly.py", imports) == [
        {"module": "os", "names": [], "level": 0, "line": 1},
        {"module": "app.jobs.helpers", "names": ["helper"], "level": 0, "line": 2,
         "aliases": {"h": "helper"}},
        {"module": "app.jobs", "names": ["utils"], "level": 0, "line": 3},
        {"module": "app.shared", "names": ["X"], "level": 0, "line": 4},
        {"module": None, "names": ["deep"], "level": 4, "line": 5},
    ]
    assert resolve_relative_imports(
        "app/__init__.py",
        [{"module": "models", "names": ["Widget"], "level": 1, "line": 1}],
    ) == [{"module": "app.models", "names": ["Widget"], "level": 0, "line": 1}]


def test_run_scan_resolves_relative_imports_for_calls_constants_and_file_imports(
    tmp_path,
):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "helpers.py").write_text(
        "MAX_RETRIES = 3\n"
        "\n"
        "\n"
        "def helper():\n"
        "    return 1\n"
    )
    (project_root / "app" / "service.py").write_text(
        "from .helpers import helper, MAX_RETRIES\n"
        "from . import helpers\n"
        "\n"
        "\n"
        "def by_name():\n"
        "    return helper(), MAX_RETRIES\n"
        "\n"
        "\n"
        "def by_module():\n"
        "    return helpers.helper()\n"
    )
    (project_root / "app" / "jobs").mkdir()
    (project_root / "app" / "jobs" / "nightly.py").write_text(
        "from ..helpers import helper\n"
        "\n"
        "\n"
        "def run():\n"
        "    return helper()\n"
    )

    run_scan(conn, project_root, config)

    callers = conn.execute(
        """
        SELECT s.qualified_name, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'calls'
          AND r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND t.qualified_name = 'app.helpers.helper'
        ORDER BY s.qualified_name
        """
    ).fetchall()
    importers = conn.execute(
        """
        SELECT s.path FROM relationships r
        JOIN files s ON s.id = r.source_entity_id
        JOIN files t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'imports'
          AND r.source_entity_type = 'file' AND r.target_entity_type = 'file'
          AND t.path = 'app/helpers.py'
        ORDER BY s.path
        """
    ).fetchall()

    assert callers == [
        ("app.jobs.nightly.run", "high"),
        ("app.service.by_module", "high"),
        ("app.service.by_name", "high"),
    ]
    assert _reference_confidence(
        conn, "app.service.by_name", "app.helpers.MAX_RETRIES"
    ) == [("high",)]
    assert importers == [("app/jobs/nightly.py",), ("app/service.py",)]


def test_run_scan_persists_static_call_relationship_from_method_to_module_function(
    tmp_path,
):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "workflow.py").write_text(
        "def helper():\n"
        "    return 'done'\n"
        "\n"
        "\n"
        "class Service:\n"
        "    def run(self):\n"
        "        return helper()\n"
    )

    run_scan(conn, project_root, config)

    caller_id = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'app.workflow.Service.run'"
    ).fetchone()[0]
    callee_id = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'app.workflow.helper'"
    ).fetchone()[0]
    relationship = conn.execute(
        """
        SELECT relationship_type, confidence FROM relationships
        WHERE source_entity_type = 'symbol' AND source_entity_id = ?
          AND target_entity_type = 'symbol' AND target_entity_id = ?
        """,
        (caller_id, callee_id),
    ).fetchone()

    assert relationship == ("calls", "high")


def test_run_scan_persists_static_call_relationship_from_nested_function(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "workflow.py").write_text(
        "def helper():\n"
        "    return 'done'\n"
        "\n"
        "\n"
        "def outer():\n"
        "    def inner():\n"
        "        return helper()\n"
        "\n"
        "    return inner\n"
    )

    run_scan(conn, project_root, config)

    caller_id = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'app.workflow.outer.inner'"
    ).fetchone()[0]
    callee_id = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'app.workflow.helper'"
    ).fetchone()[0]
    relationship = conn.execute(
        """
        SELECT relationship_type, confidence FROM relationships
        WHERE source_entity_type = 'symbol' AND source_entity_id = ?
          AND target_entity_type = 'symbol' AND target_entity_id = ?
        """,
        (caller_id, callee_id),
    ).fetchone()

    assert relationship == ("calls", "high")


def test_run_scan_continues_indexing_when_a_python_file_has_syntax_error(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "broken.py").write_text("def broken(:\n    pass\n")

    run_scan(conn, project_root, config)

    qualified_names = {
        row[0] for row in conn.execute("SELECT qualified_name FROM symbols").fetchall()
    }

    assert "app.models.Widget" in qualified_names
    assert "app.broken" not in qualified_names


def test_run_scan_enriches_symbols_with_django_framework_metadata(tmp_path):
    import json

    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    # Add a Django model to the fixture
    models_py = project_root / "app" / "models.py"
    models_py.write_text(
        "from django.db import models\n"
        "\n"
        "class User(models.Model):\n"
        "    name = models.CharField(max_length=100)\n"
    )

    run_scan(conn, project_root, config)

    # Check that Django model was indexed and should have framework metadata
    symbols = conn.execute(
        "SELECT qualified_name, metadata_json FROM symbols WHERE qualified_name = 'app.models.User'"
    ).fetchall()

    assert len(symbols) == 1
    qualified_name, metadata_json = symbols[0]
    # After integration, metadata_json should contain {"framework_kind": "django_model"}
    if metadata_json:
        metadata = json.loads(metadata_json)
        assert metadata.get("framework_kind") == "django_model"


def test_run_scan_tags_symbols_in_django_migration_files(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    migrations = project_root / "app" / "migrations"
    migrations.mkdir()
    (migrations / "__init__.py").write_text("")
    (migrations / "0001_initial.py").write_text(
        "class Migration:\n    dependencies = []\n"
    )

    run_scan(conn, project_root, config)

    def framework_kind_of(path):
        rows = conn.execute(
            "SELECT s.metadata_json FROM symbols s JOIN files f ON f.id = s.file_id"
            " WHERE f.path = ? AND s.kind = 'class'",
            (path,),
        ).fetchall()
        assert rows
        return {json.loads(row[0] or "{}").get("framework_kind") for row in rows}

    assert framework_kind_of("app/migrations/0001_initial.py") == {"django_migration"}
    assert "django_migration" not in framework_kind_of("app/models.py")


def test_run_scan_enriches_only_current_project_symbols(tmp_path):
    """Enrichment should only affect symbols in current project, not other projects."""
    import json

    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    # First scan: create project and symbols
    run_scan(conn, project_root, config)

    # Manually insert a symbol for a different project (simulating multi-project DB)
    other_project_id = conn.execute(
        "INSERT INTO projects (root_path, created_at) VALUES (?, ?) RETURNING id",
        ("/other/project", datetime.now(timezone.utc).isoformat()),
    ).fetchone()[0]
    other_file_id = conn.execute(
        "INSERT INTO files (project_id, path, language) VALUES (?, ?, ?) RETURNING id",
        (other_project_id, "models.py", "python"),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO symbols (file_id, name, qualified_name, kind, metadata_json) VALUES (?, ?, ?, ?, ?)",
        (other_file_id, "User", "other_project.models.User", "class", '{"bases": ["models.Model"]}'),
    )
    conn.commit()

    # Add Django model to current project and re-scan
    models_py = project_root / "app" / "models.py"
    models_py.write_text(
        "from django.db import models\n"
        "class Product(models.Model):\n"
        "    name = models.CharField(max_length=100)\n"
    )
    run_scan(conn, project_root, config)

    # Check: Current project's Product should be enriched
    product = conn.execute(
        "SELECT metadata_json FROM symbols WHERE qualified_name = 'app.models.Product'"
    ).fetchone()
    if product and product[0]:
        metadata = json.loads(product[0])
        assert metadata.get("framework_kind") == "django_model"

    # Check: Other project's User should NOT be enriched (isolation preserved)
    other_user = conn.execute(
        "SELECT metadata_json FROM symbols WHERE qualified_name = 'other_project.models.User'"
    ).fetchone()
    if other_user and other_user[0]:
        metadata = json.loads(other_user[0])
        # Should still have only "bases", no "framework_kind" added
        assert "framework_kind" not in metadata, "Other project symbol was incorrectly enriched!"


def test_run_scan_handles_malformed_metadata_json(tmp_path):
    """Enrichment should gracefully handle malformed metadata_json without crashing."""
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    # Manually insert a symbol with malformed JSON
    file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'app/models.py' LIMIT 1"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO symbols (file_id, name, qualified_name, kind, metadata_json) VALUES (?, ?, ?, ?, ?)",
        (file_id, "Broken", "app.models.Broken", "class", "{invalid json"),
    )
    conn.commit()

    # Re-scan should not crash despite malformed metadata
    run_scan(conn, project_root, config)

    # Existing symbols should still be enriched
    widget = conn.execute(
        "SELECT metadata_json FROM symbols WHERE qualified_name = 'app.models.Widget'"
    ).fetchone()
    assert widget is not None  # Widget should still exist


def test_indexer_discovers_pytest_tests(tmp_path):
    """Test files are indexed and stored in the tests table during scan."""
    project_root = tmp_path / "test_project"
    project_root.mkdir()
    (project_root / ".project-mcp").mkdir()

    # Create a test file
    test_file = project_root / "tests" / "test_example.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("""\
def test_something():
    assert True

class TestExample:
    def test_method(self):
        assert True
""")

    # Create a source file for association
    src_file = project_root / "src" / "example.py"
    src_file.parent.mkdir(parents=True)
    src_file.write_text("def something(): pass")

    conn = get_connection(project_root)
    config = load_config(project_root)

    run_scan(conn, project_root, config)

    # Check that tests were indexed
    tests = conn.execute("SELECT COUNT(*) FROM tests").fetchone()[0]
    assert tests > 0, "No tests found in database after indexing"


def test_ensure_fresh_index_runs_full_scan_when_never_indexed(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    ensure_fresh_index(conn, project_root, config)

    assert get_index_status(conn)["status"] == "fresh"
    paths = {row[0] for row in conn.execute("SELECT path FROM files").fetchall()}
    assert "app/models.py" in paths


def test_ensure_fresh_index_refreshes_when_stale(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    run_scan(conn, project_root, config)

    import time

    time.sleep(0.01)
    app_file = project_root / "app" / "models.py"
    app_file.write_text(app_file.read_text() + "\n\nclass FreshlyAdded:\n    pass\n")

    ensure_fresh_index(conn, project_root, config)

    row = conn.execute(
        "SELECT name FROM symbols WHERE name = 'FreshlyAdded'"
    ).fetchone()
    assert row is not None
    assert get_index_status(conn)["status"] == "fresh"


def test_ensure_fresh_index_is_a_noop_when_already_fresh(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    run_scan(conn, project_root, config)
    indexed_at_before = {
        row[0]: row[1]
        for row in conn.execute("SELECT path, indexed_at FROM files").fetchall()
    }

    ensure_fresh_index(conn, project_root, config)

    indexed_at_after = {
        row[0]: row[1]
        for row in conn.execute("SELECT path, indexed_at FROM files").fetchall()
    }
    assert indexed_at_before == indexed_at_after


def test_run_scan_persists_git_change_history_for_indexed_files(tmp_path):
    import subprocess

    project_root = _copy_fixture(tmp_path)
    subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=project_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )

    conn = get_connection(project_root)
    config = load_config(project_root)

    run_scan(conn, project_root, config)

    file_id = conn.execute(
        "SELECT id FROM files WHERE path = ?", ("app/models.py",)
    ).fetchone()[0]
    row = conn.execute(
        "SELECT change_count, last_changed FROM git_facts WHERE file_id = ?",
        (file_id,),
    ).fetchone()

    assert row is not None
    assert row[0] >= 1
    assert row[1] is not None


def test_run_scan_persists_git_facts_using_configured_history_limit(tmp_path):
    project_root = build_git_fixture("churn-fixture", tmp_path)
    (project_root / ".project-mcp").mkdir()
    (project_root / ".project-mcp" / "config.toml").write_text(
        "git_history_limit = 2\n"
    )

    conn = get_connection(project_root)
    config = load_config(project_root)

    run_scan(conn, project_root, config)

    row = conn.execute(
        "SELECT gf.change_count FROM git_facts gf "
        "JOIN files f ON f.id = gf.file_id WHERE f.path = ?",
        ("file1.py",),
    ).fetchone()

    assert row is not None
    assert row[0] == 2


def test_run_scan_persists_explicit_architecture_facts_from_docs(tmp_path):
    project_root = tmp_path / "project"
    (project_root / "docs" / "architecture").mkdir(parents=True)
    (project_root / "docs" / "architecture" / "payments.md").write_text(
        "# Payments\n\n## Depends on shared\n\nSome text.\n"
    )

    conn = get_connection(project_root)
    config = load_config(project_root)

    run_scan(conn, project_root, config)

    rows = conn.execute(
        "SELECT subject, predicate, object, origin, source FROM architecture_facts"
    ).fetchall()

    assert (
        "Depends on shared",
        "documented_in",
        "docs/architecture/payments.md",
        "explicit",
        "docs/architecture/payments.md",
    ) in rows


def test_run_scan_persists_large_file_legacy_signal(tmp_path):
    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "big.py").write_text("x = 1\ny = 2\nz = 3\n")
    (project_root / ".project-mcp").mkdir()
    (project_root / ".project-mcp" / "config.toml").write_text("large_file_lines = 1\n")

    conn = get_connection(project_root)
    config = load_config(project_root)

    run_scan(conn, project_root, config)

    rows = conn.execute(
        "SELECT target, signal, severity, confidence, evidence FROM legacy_signals"
        " WHERE signal = 'large_file'"
    ).fetchall()

    assert len(rows) == 1
    target, signal, severity, confidence, evidence = rows[0]
    assert target == "app/big.py"
    assert severity == "medium"
    assert confidence == "high"
    assert json.loads(evidence)


def test_run_scan_persists_explicit_legacy_path_signal(tmp_path):
    project_root = tmp_path / "project"
    (project_root / "app" / "legacy").mkdir(parents=True)
    (project_root / "app" / "legacy" / "old.py").write_text("x = 1\n")
    (project_root / ".project-mcp").mkdir()
    (project_root / ".project-mcp" / "config.toml").write_text(
        'legacy_paths = ["app/legacy/"]\n'
    )

    conn = get_connection(project_root)
    config = load_config(project_root)

    run_scan(conn, project_root, config)

    rows = conn.execute(
        "SELECT target FROM legacy_signals WHERE signal = 'explicit_legacy_path'"
    ).fetchall()

    assert ("app/legacy/old.py",) in rows


def test_run_scan_persists_weak_test_relationship_signal_for_untested_file(tmp_path):
    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "__init__.py").write_text("")
    (project_root / "app" / "untested.py").write_text("def do_thing():\n    pass\n")

    conn = get_connection(project_root)
    config = load_config(project_root)

    run_scan(conn, project_root, config)

    rows = conn.execute(
        "SELECT target FROM legacy_signals WHERE signal = 'weak_test_relationship'"
    ).fetchall()

    assert ("app/untested.py",) in rows


def test_run_scan_replaces_legacy_signals_on_rescan_without_duplicating(tmp_path):
    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "big.py").write_text("x = 1\ny = 2\nz = 3\n")
    (project_root / ".project-mcp").mkdir()
    (project_root / ".project-mcp" / "config.toml").write_text("large_file_lines = 1\n")

    conn = get_connection(project_root)
    config = load_config(project_root)

    run_scan(conn, project_root, config)
    run_scan(conn, project_root, config)

    rows = conn.execute(
        "SELECT target FROM legacy_signals WHERE signal = 'large_file'"
        " AND target = 'app/big.py'"
    ).fetchall()

    assert len(rows) == 1


def _git(project_root, *args):
    import subprocess

    subprocess.run(
        ["git", *args], cwd=project_root, check=True, capture_output=True
    )


def test_run_scan_reads_git_history_in_one_pass_with_per_file_results(
    tmp_path, monkeypatch
):
    """A scan reads git history with a single `git log`, however many files
    there are, and stores the same facts the per-file git queries report."""
    import subprocess

    from project_mcp.analyzers.generic import git as git_module
    from project_mcp.analyzers.generic.git import (
        get_file_change_count,
        get_file_last_changed,
        get_files_changed_together,
    )

    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    names = [f"app/m{i}.py" for i in range(8)]
    _git(project_root, "init")
    _git(project_root, "config", "user.email", "test@example.com")
    _git(project_root, "config", "user.name", "Test")
    for name in names:
        (project_root / name).write_text("x = 1\n")
    _git(project_root, "add", ".")
    _git(project_root, "commit", "-m", "initial")
    for name in names[:7]:
        (project_root / name).write_text("x = 2\n")
    _git(project_root, "commit", "-am", "wide change")
    (project_root / names[0]).write_text("x = 3\n")
    _git(project_root, "commit", "-am", "narrow change")
    (project_root / "app" / "untracked.py").write_text("x = 1\n")

    config = load_config(project_root)
    expected_facts = {
        path: (
            get_file_change_count(project_root, path, config=config),
            get_file_last_changed(project_root, path),
        )
        for path in names + ["app/untracked.py"]
    }
    expected_coupled = {
        path
        for path in names + ["app/untracked.py"]
        if len(get_files_changed_together(project_root, path, config=config))
        > config.high_temporal_coupling_count
    }

    git_logs = []
    real_run = subprocess.run

    def counting_run(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "log"]:
            git_logs.append(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(git_module.subprocess, "run", counting_run)

    conn = get_connection(project_root)
    run_scan(conn, project_root, config)

    assert len(git_logs) == 1
    facts = {
        path: (count, last_changed)
        for path, count, last_changed in conn.execute(
            "SELECT f.path, g.change_count, g.last_changed"
            " FROM git_facts g JOIN files f ON f.id = g.file_id"
        ).fetchall()
    }
    assert facts == expected_facts
    coupled = {
        row[0]
        for row in conn.execute(
            "SELECT target FROM legacy_signals"
            " WHERE signal = 'high_temporal_coupling'"
        ).fetchall()
    }
    assert coupled == expected_coupled
    assert expected_coupled  # the fixture history must actually trigger it


def test_index_legacy_signals_reads_each_file_from_disk_exactly_once_for_line_counts(
    tmp_path,
):
    """Characterization test: line-count computation for structural signals reads
    each indexed file from disk exactly once per index_legacy_signals call — no
    caching, but also no redundant re-reads. Locks in the current cost so a
    future change can't silently multiply the disk I/O without a test noticing."""
    from unittest.mock import patch

    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "a.py").write_text("x = 1\n")
    (project_root / "app" / "b.py").write_text("y = 1\n")

    conn = get_connection(project_root)
    config = load_config(project_root)
    run_scan(conn, project_root, config)

    project_id = conn.execute("SELECT id FROM projects").fetchone()[0]
    file_rows = conn.execute(
        "SELECT path, id, file_kind FROM files WHERE project_id = ?", (project_id,)
    ).fetchall()
    path_to_file_id = {path: file_id for path, file_id, _ in file_rows}
    file_kinds = {path: file_kind for path, _, file_kind in file_rows}

    with patch("pathlib.Path.read_text", wraps=Path.read_text, autospec=True) as spy:
        index_legacy_signals(conn, project_id, project_root, path_to_file_id, file_kinds, config)

    assert spy.call_count == len(path_to_file_id)


def test_run_scan_links_self_method_calls_to_own_and_inherited_methods(tmp_path):
    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "svc.py").write_text(
        "class Base:\n"
        "    def shared(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "class Service(Base):\n"
        "    status = 'new'\n"
        "\n"
        "    def helper(self):\n"
        "        return self.status\n"
        "\n"
        "    def run(self):\n"
        "        self.shared()\n"
        "        self.missing()\n"
        "        return self.helper()\n"
        "\n"
        "    def nested(self):\n"
        "        def inner():\n"
        "            return self.helper()\n"
        "        return inner\n"
    )
    conn = get_connection(project_root)

    run_scan(conn, project_root, load_config(project_root))

    edges = conn.execute(
        """
        SELECT s.qualified_name, r.relationship_type, r.confidence, t.qualified_name
        FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND r.relationship_type IN ('calls', 'references')
        ORDER BY 1, 4
        """
    ).fetchall()
    assert edges == [
        ("app.svc.Service.helper", "references", "high", "app.svc.Service.status"),
        ("app.svc.Service.nested.inner", "calls", "high", "app.svc.Service.helper"),
        ("app.svc.Service.run", "calls", "high", "app.svc.Base.shared"),
        ("app.svc.Service.run", "calls", "high", "app.svc.Service.helper"),
    ]


def _inherits_edges(conn):
    return conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'inherits'
          AND r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
        ORDER BY 1, 2
        """
    ).fetchall()


def test_run_scan_links_classes_to_bases_imported_from_other_files(tmp_path):
    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "__init__.py").write_text("")
    (project_root / "app" / "base.py").write_text(
        "class Base:\n    pass\n\n\nclass Mixin:\n    pass\n"
    )
    (project_root / "app" / "models.py").write_text(
        "import app.base\n"
        "from app import base\n"
        "from .base import Base as Root\n"
        "\n"
        "\n"
        "class Local:\n"
        "    pass\n"
        "\n"
        "\n"
        "class ByName(Root):\n"
        "    pass\n"
        "\n"
        "\n"
        "class ByModule(base.Mixin, Local):\n"
        "    pass\n"
        "\n"
        "\n"
        "class ByDottedModule(app.base.Base, Unknown):\n"
        "    pass\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    expected = [
        ("app.models.ByDottedModule", "app.base.Base"),
        ("app.models.ByModule", "app.base.Mixin"),
        ("app.models.ByModule", "app.models.Local"),
        ("app.models.ByName", "app.base.Base"),
    ]
    assert _inherits_edges(conn) == expected

    (project_root / "app" / "base.py").write_text(
        "class Base:\n    x = 1\n\n\nclass Mixin:\n    pass\n"
    )
    refresh_index(conn, project_root, config)

    assert _inherits_edges(conn) == expected


def _call_edges_from(conn, caller: str):
    return conn.execute(
        """
        SELECT t.qualified_name FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'calls' AND s.qualified_name = ?
        ORDER BY 1
        """,
        (caller,),
    ).fetchall()


def test_run_scan_links_self_method_calls_to_methods_inherited_across_files(tmp_path):
    """The subclass file sorts first, so its bases' own cross-file inherits
    edges don't exist yet when it is processed in file order."""
    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "c_core.py").write_text(
        "class Root:\n"
        "    def ping(self):\n"
        "        return 1\n"
    )
    (project_root / "app" / "b_base.py").write_text(
        "from app.c_core import Root\n"
        "\n"
        "\n"
        "class Base(Root):\n"
        "    def save(self):\n"
        "        return 1\n"
    )
    (project_root / "app" / "a_models.py").write_text(
        "from app.b_base import Base\n"
        "\n"
        "\n"
        "class Model(Base):\n"
        "    def run(self):\n"
        "        self.save()\n"
        "        self.ping()\n"
        "        self.missing()\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    expected = [("app.b_base.Base.save",), ("app.c_core.Root.ping",)]
    assert _call_edges_from(conn, "app.a_models.Model.run") == expected

    (project_root / "app" / "b_base.py").write_text(
        (project_root / "app" / "b_base.py").read_text() + "\n# edited\n"
    )
    refresh_index(conn, project_root, config)

    assert _call_edges_from(conn, "app.a_models.Model.run") == expected


def test_run_scan_links_method_calls_on_constructed_and_annotated_objects(tmp_path):
    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "models.py").write_text(
        "class Payment:\n"
        "    def charge(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "class Refund(Payment):\n"
        "    pass\n"
    )
    (project_root / "app" / "service.py").write_text(
        "import app.models as m\n"
        "from app.models import Payment, Refund\n"
        "\n"
        "\n"
        "class Local:\n"
        "    def go(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "def by_constructor():\n"
        "    p = Payment()\n"
        "    return p.charge()\n"
        "\n"
        "\n"
        "def by_inherited():\n"
        "    r = Refund()\n"
        "    return r.charge()\n"
        "\n"
        "\n"
        "def by_module():\n"
        "    p = m.Payment()\n"
        "    return p.charge()\n"
        "\n"
        "\n"
        "def by_annotation(p: Payment, local: Local | None):\n"
        "    p.charge()\n"
        "    return local.go()\n"
        "\n"
        "\n"
        "def by_local_class():\n"
        "    local = Local()\n"
        "    return local.go()\n"
        "\n"
        "\n"
        "def reassigned():\n"
        "    x = Payment()\n"
        "    x = Local()\n"
        "    return x.charge()\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    edges = conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'calls' AND s.qualified_name LIKE 'app.service.%'
          AND t.kind = 'method'
        ORDER BY 1, 2
        """
    ).fetchall()
    assert edges == [
        ("app.service.by_annotation", "app.models.Payment.charge", "high"),
        ("app.service.by_annotation", "app.service.Local.go", "high"),
        ("app.service.by_constructor", "app.models.Payment.charge", "high"),
        ("app.service.by_inherited", "app.models.Payment.charge", "high"),
        ("app.service.by_local_class", "app.service.Local.go", "high"),
        ("app.service.by_module", "app.models.Payment.charge", "high"),
        # Conflicting types give no high-confidence edge, only the name-based guess.
        ("app.service.reassigned", "app.models.Payment.charge", "low"),
    ]


def test_run_scan_indexes_a_file_that_is_not_valid_utf8(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "legacy.py").write_bytes(
        b"def cafe():\n    return 1  # caf\xe9\n"
    )

    run_scan(conn, project_root, config)

    qualified_names = {
        row[0] for row in conn.execute("SELECT qualified_name FROM symbols").fetchall()
    }
    assert "app.legacy.cafe" in qualified_names
    assert "app.models.Widget" in qualified_names


def test_run_scan_links_method_calls_made_on_a_class_itself(tmp_path):
    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "checks.py").write_text(
        "class Base:\n"
        "    @classmethod\n"
        "    def inherited(cls):\n"
        "        return 1\n"
        "\n"
        "\n"
        "class Checker(Base):\n"
        "    @staticmethod\n"
        "    def is_ok(value):\n"
        "        return True\n"
    )
    (project_root / "app" / "service.py").write_text(
        "import app.checks as c\n"
        "from app.checks import Checker\n"
        "\n"
        "\n"
        "class Local:\n"
        "    @staticmethod\n"
        "    def go():\n"
        "        return 1\n"
        "\n"
        "\n"
        "def by_imported_class():\n"
        "    return Checker.is_ok(1)\n"
        "\n"
        "\n"
        "def by_module_qualified_class():\n"
        "    return c.Checker.is_ok(1)\n"
        "\n"
        "\n"
        "def by_inherited_method():\n"
        "    return Checker.inherited()\n"
        "\n"
        "\n"
        "def by_local_class():\n"
        "    return Local.go()\n"
        "\n"
        "\n"
        "def unknown_method():\n"
        "    return Checker.missing()\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    edges = conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'calls' AND s.qualified_name LIKE 'app.service.%'
        ORDER BY s.qualified_name, t.qualified_name
        """
    ).fetchall()

    assert edges == [
        ("app.service.by_imported_class", "app.checks.Checker.is_ok", "high"),
        ("app.service.by_inherited_method", "app.checks.Base.inherited", "high"),
        ("app.service.by_local_class", "app.service.Local.go", "high"),
        ("app.service.by_module_qualified_class", "app.checks.Checker.is_ok", "high"),
    ]


def test_run_scan_links_calls_on_untyped_objects_by_method_name_with_low_confidence(
    tmp_path,
):
    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    crowded = "".join(
        f"class Crowd{i}:\n    def common(self):\n        return {i}\n\n\n" for i in range(4)
    )
    (project_root / "app" / "models.py").write_text(
        "class Order:\n"
        "    def refund(self):\n"
        "        return 1\n"
        "\n"
        "\n" + crowded
    )
    (project_root / "app" / "elsewhere.py").write_text(
        "class Stranger:\n    def only_here(self):\n        return 1\n"
    )
    (project_root / "app" / "views.py").write_text(
        "from app.models import Order\n"
        "\n"
        "\n"
        "class View:\n"
        "    def post(self, obj):\n"
        "        return obj.refund()\n"
        "\n"
        "\n"
        "def typed():\n"
        "    order = Order()\n"
        "    return order.refund()\n"
        "\n"
        "\n"
        "def unknown_method(obj):\n"
        "    return obj.nothing_like_it()\n"
        "\n"
        "\n"
        "def ambiguous_method(obj):\n"
        "    return obj.common()\n"
        "\n"
        "\n"
        "def not_imported(obj):\n"
        "    return obj.only_here()\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    edges = conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'calls' AND s.qualified_name LIKE 'app.views.%'
          AND t.kind = 'method'
        ORDER BY s.qualified_name, t.qualified_name
        """
    ).fetchall()

    assert edges == [
        ("app.views.View.post", "app.models.Order.refund", "low"),
        ("app.views.typed", "app.models.Order.refund", "high"),
    ]


def test_run_scan_links_reads_of_imported_and_local_classes_to_the_reading_symbol(
    tmp_path,
):
    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "models.py").write_text(
        "class Watch:\n    objects = None\n\n\nclass Unused:\n    pass\n"
    )
    (project_root / "app" / "service.py").write_text(
        "import app.models as m\n"
        "from app.models import Watch\n"
        "\n"
        "\n"
        "class Local:\n"
        "    pass\n"
        "\n"
        "\n"
        "def by_import():\n"
        "    return Watch.objects\n"
        "\n"
        "\n"
        "def by_local_class():\n"
        "    return Local\n"
        "\n"
        "\n"
        "def by_own_method(self_like=None):\n"
        "    return [Watch, Local]\n"
        "\n"
        "\n"
        "def unrelated():\n"
        "    return 1\n"
    )
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    edges = conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'references' AND t.kind = 'class'
          AND r.source_entity_type = 'symbol' AND s.qualified_name LIKE 'app.service.%'
        ORDER BY 1, 2
        """
    ).fetchall()

    assert edges == [
        ("app.service.by_import", "app.models.Watch", "high"),
        ("app.service.by_local_class", "app.service.Local", "high"),
        ("app.service.by_own_method", "app.models.Watch", "high"),
        ("app.service.by_own_method", "app.service.Local", "high"),
    ]


def test_run_scan_links_class_attribute_reference_only_to_that_classs_field(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "models.py").write_text(
        "class Promo:\n    objects = None\n\n\nclass Watch:\n    pass\n"
    )
    (project_root / "app" / "views.py").write_text(
        "from app.models import Promo, Watch\n"
        "\n"
        "\n"
        "def watches():\n"
        "    return Watch.objects\n"
        "\n"
        "\n"
        "def promos():\n"
        "    return Promo.objects\n"
    )

    run_scan(conn, project_root, config)

    rows = conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'references'
          AND r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND t.kind = 'field' AND s.qualified_name LIKE 'app.views.%'
        """
    ).fetchall()

    assert rows == [("app.views.promos", "app.models.Promo.objects", "low")]


def test_run_scan_does_not_guess_a_field_for_an_unresolvable_class_name(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "models.py").write_text(
        "class Promo:\n    objects = None\n"
    )
    (project_root / "app" / "views.py").write_text(
        "from app.models import Promo\n"
        "from elsewhere import Watch\n"
        "\n"
        "\n"
        "def external():\n"
        "    return Watch.objects\n"
        "\n"
        "\n"
        "def untyped(row):\n"
        "    return row.objects\n"
    )

    run_scan(conn, project_root, config)

    rows = conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'references'
          AND r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND t.kind = 'field' AND s.qualified_name LIKE 'app.views.%'
        """
    ).fetchall()

    assert rows == [("app.views.untyped", "app.models.Promo.objects")]


def test_run_scan_links_class_attribute_access_within_the_same_file(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "heads.py").write_text(
        "class Base:\n"
        "    inherited = 1\n"
        "\n"
        "\n"
        "class Heads(Base):\n"
        "    objects = None\n"
        "\n"
        "    def active(self):\n"
        "        return Heads.objects, Heads.inherited, Heads.missing\n"
    )

    run_scan(conn, project_root, config)

    rows = conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'references'
          AND r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND t.kind = 'field' AND s.qualified_name LIKE 'app.heads.%'
        ORDER BY t.qualified_name
        """
    ).fetchall()

    assert rows == [
        ("app.heads.Heads.active", "app.heads.Base.inherited", "high"),
        ("app.heads.Heads.active", "app.heads.Heads.objects", "high"),
    ]


def test_run_scan_links_a_dotted_nested_class_attribute_in_the_same_file(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "nested.py").write_text(
        "class Outer:\n"
        "    class Inner:\n"
        "        limit = 1\n"
        "\n"
        "    def read(self):\n"
        "        return Outer.Inner.limit, unknown.thing.limit, Outer.Inner.nope\n"
    )

    run_scan(conn, project_root, config)

    rows = conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'references'
          AND r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND t.kind = 'field' AND s.qualified_name LIKE 'app.nested.%'
        """
    ).fetchall()

    assert rows == [
        ("app.nested.Outer.read", "app.nested.Outer.Inner.limit", "high"),
    ]


def test_run_scan_links_a_class_to_the_classes_its_body_reads(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "brands.py").write_text("class Brand:\n    pass\n")
    (project_root / "app" / "watch.py").write_text(
        "from app.brands import Brand\n"
        "\n"
        "\n"
        "class Local:\n"
        "    pass\n"
        "\n"
        "\n"
        "class Watch:\n"
        "    brand = FK(Brand)\n"
        "    other = FK(Local)\n"
    )

    run_scan(conn, project_root, config)

    rows = conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'references'
          AND r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND s.qualified_name = 'app.watch.Watch'
        ORDER BY t.qualified_name
        """
    ).fetchall()

    assert rows == [
        ("app.watch.Watch", "app.brands.Brand", "high"),
        ("app.watch.Watch", "app.watch.Local", "high"),
    ]


def test_run_scan_links_calls_made_on_a_constructor_expression(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "models.py").write_text(
        "class Payment:\n    def charge(self):\n        return 1\n"
    )
    (project_root / "app" / "service.py").write_text(
        "from app.models import Payment\n\n\n"
        "def run():\n    return Payment().charge()\n"
    )

    run_scan(conn, project_root, config)

    edges = conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'calls' AND s.qualified_name = 'app.service.run'
          AND t.qualified_name = 'app.models.Payment.charge'
        """
    ).fetchall()

    assert edges == [("app.service.run", "app.models.Payment.charge", "high")]


def test_resolve_source_root_imports_prefixes_modules_found_under_a_source_root():
    path_to_file_id = {
        "src/shop/billing.py": 1,
        "src/shop/tests/test_billing.py": 2,
        "tools/report.py": 3,
    }
    imports = [
        {"module": "shop.billing", "names": ["Invoice"], "level": 0, "line": 1},
        {"module": "shop", "names": ["billing"], "level": 0, "line": 2},
        {"module": "tools.report", "names": [], "level": 0, "line": 3},
        {"module": "os", "names": [], "level": 0, "line": 4},
        {"module": None, "names": ["deep"], "level": 4, "line": 5},
    ]

    assert resolve_source_root_imports(imports, ["src"], path_to_file_id) == [
        {"module": "src.shop.billing", "names": ["Invoice"], "level": 0, "line": 1},
        {"module": "src.shop", "names": ["billing"], "level": 0, "line": 2},
        {"module": "tools.report", "names": [], "level": 0, "line": 3},
        {"module": "os", "names": [], "level": 0, "line": 4},
        {"module": None, "names": ["deep"], "level": 4, "line": 5},
    ]


def test_run_scan_links_calls_through_imports_relative_to_a_source_root(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    (tmp_path / ".project-mcp" / "config.toml").write_text('source_roots = ["src"]\n')
    (tmp_path / "src" / "shop").mkdir(parents=True)
    (tmp_path / "src" / "shop" / "billing.py").write_text(
        "def total():\n    return 1\n"
    )
    (tmp_path / "src" / "shop" / "test_billing.py").write_text(
        "from shop.billing import total\n\n\ndef test_total():\n    assert total()\n"
    )
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    edges = conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'calls'
          AND r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
        """
    ).fetchall()
    assert ("src.shop.test_billing.test_total", "src.shop.billing.total") in edges


def test_refresh_index_links_calls_through_imports_relative_to_a_source_root(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    (tmp_path / ".project-mcp" / "config.toml").write_text('source_roots = ["src"]\n')
    (tmp_path / "src" / "shop").mkdir(parents=True)
    (tmp_path / "src" / "shop" / "billing.py").write_text(
        "def total():\n    return 1\n"
    )
    test_file = tmp_path / "src" / "shop" / "test_billing.py"
    test_file.write_text("def test_nothing():\n    assert True\n")
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    run_scan(conn, tmp_path, config)
    test_file.write_text(
        "from shop.billing import total\n\n\ndef test_total():\n    assert total()\n"
    )

    refresh_index(conn, tmp_path, config)

    edges = conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'calls'
          AND r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
        """
    ).fetchall()
    assert ("src.shop.test_billing.test_total", "src.shop.billing.total") in edges


def test_refresh_index_keeps_source_root_calls_from_an_unchanged_importer(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    (tmp_path / ".project-mcp" / "config.toml").write_text('source_roots = ["src"]\n')
    (tmp_path / "src" / "shop").mkdir(parents=True)
    billing = tmp_path / "src" / "shop" / "billing.py"
    billing.write_text("def total():\n    return 1\n")
    (tmp_path / "src" / "shop" / "test_billing.py").write_text(
        "from shop.billing import total\n\n\ndef test_total():\n    assert total()\n"
    )
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    run_scan(conn, tmp_path, config)
    billing.write_text("def total():\n    return 2\n")

    refresh_index(conn, tmp_path, config)

    edges = conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'calls'
          AND r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
        """
    ).fetchall()
    assert ("src.shop.test_billing.test_total", "src.shop.billing.total") in edges


def test_run_scan_links_test_files_to_modules_under_a_source_root(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    (tmp_path / ".project-mcp" / "config.toml").write_text('source_roots = ["src"]\n')
    (tmp_path / "src" / "shop" / "tests").mkdir(parents=True)
    (tmp_path / "src" / "shop" / "billing.py").write_text(
        "def total():\n    return 1\n"
    )
    (tmp_path / "src" / "shop" / "tests" / "test_billing.py").write_text(
        "from shop.billing import total\n\n\ndef test_total():\n    assert total()\n"
    )
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    edges = conn.execute(
        """
        SELECT s.path, t.path, r.confidence FROM relationships r
        JOIN files s ON s.id = r.source_entity_id
        JOIN files t ON t.id = r.target_entity_id
        WHERE r.relationship_type = 'tests'
        """
    ).fetchall()
    assert edges == [
        ("src/shop/tests/test_billing.py", "src/shop/billing.py", "high")
    ]


def test_resolve_source_root_imports_normalizes_how_a_source_root_is_written():
    path_to_file_id = {"src/shop/billing.py": 1}
    imports = [{"module": "shop.billing", "names": [], "level": 0}]

    rewritten = {
        root: resolve_source_root_imports(imports, [root], path_to_file_id)[0]["module"]
        for root in ("./src", "src/", "./src/", "src")
    }

    assert set(rewritten.values()) == {"src.shop.billing"}


def test_resolve_source_root_imports_prefixes_a_package_imported_by_name():
    path_to_file_id = {"src/shop/__init__.py": 1}
    imports = [{"module": "shop", "names": [], "level": 0}]

    (rewritten,) = resolve_source_root_imports(imports, ["src"], path_to_file_id)

    assert rewritten["module"] == "src.shop"


def test_resolve_source_root_imports_prefers_the_first_source_root_that_resolves():
    path_to_file_id = {"src/shop/billing.py": 1, "lib/shop/billing.py": 2}
    imports = [{"module": "shop.billing", "names": [], "level": 0}]

    modules = [
        resolve_source_root_imports(imports, roots, path_to_file_id)[0]["module"]
        for roots in (["src", "lib"], ["lib", "src"])
    ]

    assert modules == ["src.shop.billing", "lib.shop.billing"]


def _django_checkout_app(root: Path) -> Path:
    (root / ".project-mcp").mkdir()
    (root / ".project-mcp" / "config.toml").write_text('source_roots = ["src"]\n')
    app = root / "src" / "shop" / "checkout"
    (app / "tests").mkdir(parents=True)
    (app / "views.py").write_text(
        "class CardPayment:\n    def get(self, request):\n        return None\n"
    )
    (app / "urls.py").write_text(
        "from django.urls import path\n"
        "\n"
        "from shop.checkout.views import CardPayment\n"
        "\n"
        'app_name = "checkout"\n'
        "\n"
        "urlpatterns = [\n"
        '    path("card/", CardPayment.as_view(), name="card-payment"),\n'
        "]\n"
    )
    (app / "tests" / "test_views.py").write_text(
        "from django.urls import reverse\n"
        "\n"
        "\n"
        "def test_shows_the_form(client):\n"
        '    assert client.get(reverse("checkout:card-payment"))\n'
    )
    return root


def _url_reverse_edges(conn) -> list[tuple]:
    return conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name, r.relationship_type,
               r.confidence, r.evidence_json
        FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND r.evidence_json = '["url_reverse"]'
        """
    ).fetchall()


def test_run_scan_links_tests_to_the_views_their_reversed_url_names_route_to(tmp_path):
    _django_checkout_app(tmp_path)
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    assert _url_reverse_edges(conn) == [
        (
            "src.shop.checkout.tests.test_views.test_shows_the_form",
            "src.shop.checkout.views.CardPayment",
            "references",
            "high",
            '["url_reverse"]',
        )
    ]


def test_refresh_index_keeps_url_reverse_links_to_a_view_that_changed(tmp_path):
    _django_checkout_app(tmp_path)
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    run_scan(conn, tmp_path, config)
    (tmp_path / "src" / "shop" / "checkout" / "views.py").write_text(
        "class CardPayment:\n    def get(self, request):\n        return 'changed'\n"
    )

    refresh_index(conn, tmp_path, config)

    assert [edge[:2] for edge in _url_reverse_edges(conn)] == [
        (
            "src.shop.checkout.tests.test_views.test_shows_the_form",
            "src.shop.checkout.views.CardPayment",
        )
    ]


def test_run_scan_links_url_names_namespaced_through_nested_includes(tmp_path):
    _django_checkout_app(tmp_path)
    (tmp_path / "src" / "config").mkdir()
    (tmp_path / "src" / "config" / "urls.py").write_text(
        "from django.urls import include, path\n"
        "\n"
        'urlpatterns = [path("shop/", include("shop.urls", namespace="store"))]\n'
    )
    (tmp_path / "src" / "shop" / "urls.py").write_text(
        "from django.urls import include, path\n"
        "\n"
        'urlpatterns = [path("checkout/", include("shop.checkout.urls"))]\n'
    )
    (tmp_path / "src" / "shop" / "checkout" / "tests" / "test_views.py").write_text(
        "from django.urls import reverse\n"
        "\n"
        "\n"
        "def test_shows_the_form(client):\n"
        '    assert client.get(reverse("store:checkout:card-payment"))\n'
    )
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    assert [edge[:2] for edge in _url_reverse_edges(conn)] == [
        (
            "src.shop.checkout.tests.test_views.test_shows_the_form",
            "src.shop.checkout.views.CardPayment",
        )
    ]


def _mocked_payments_app(root: Path) -> Path:
    (root / "app").mkdir()
    (root / "app" / "payments.py").write_text(
        "class Api:\n"
        "    def _post(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "def process_payment():\n"
        "    return Api()._post()\n"
    )
    (root / "app" / "checkout.py").write_text(
        "from app.payments import process_payment\n\n\n"
        "def checkout():\n    return process_payment()\n"
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_checkout.py").write_text(
        "from unittest.mock import patch\n"
        "\n"
        "from app.checkout import checkout\n"
        "from app.payments import Api\n"
        "\n"
        "\n"
        '@patch("app.checkout.process_payment")\n'
        "def test_checkout_mocked(process_payment):\n"
        "    assert checkout()\n"
        "\n"
        "\n"
        "def test_post_mocked(mocker):\n"
        '    mocker.patch.object(Api, "_post")\n'
        "    assert checkout()\n"
    )
    return root


def _mock_edges(conn) -> list[tuple]:
    return conn.execute(
        """
        SELECT s.qualified_name, t.qualified_name, r.confidence, r.evidence_json
        FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND r.relationship_type = 'mocks'
        ORDER BY s.qualified_name
        """
    ).fetchall()


def test_run_scan_links_tests_to_the_symbols_they_patch_where_those_are_defined(
    tmp_path,
):
    _mocked_payments_app(tmp_path)
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    assert _mock_edges(conn) == [
        (
            "tests.test_checkout.test_checkout_mocked",
            "app.payments.process_payment",
            "high",
            '["mock_patch"]',
        ),
        (
            "tests.test_checkout.test_post_mocked",
            "app.payments.Api._post",
            "high",
            '["mock_patch"]',
        ),
    ]


def test_run_scan_links_tests_to_the_symbols_their_conftest_fixtures_patch(tmp_path):
    _mocked_payments_app(tmp_path)
    (tmp_path / "conftest.py").write_text(
        "import pytest\n"
        "\n"
        "from app.payments import Api\n"
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def quiet(mocker):\n"
        '    mocker.patch.object(Api, "_post")\n'
    )
    (tmp_path / "tests" / "test_quiet.py").write_text(
        "def test_quiet(quiet):\n    assert quiet is None\n"
    )
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    assert (
        "tests.test_quiet.test_quiet",
        "app.payments.Api._post",
        "high",
        '["mock_patch"]',
    ) in _mock_edges(conn)


def test_run_scan_links_a_patch_on_an_instance_to_methods_of_that_name_at_low_confidence(
    tmp_path,
):
    _mocked_payments_app(tmp_path)
    (tmp_path / "app" / "refunds.py").write_text(
        "class Refunds:\n    def _post(self):\n        return 2\n\n    def _sign(self):\n        return 3\n"
    )
    (tmp_path / "tests" / "test_instance.py").write_text(
        "from app.payments import Api\n"
        "\n"
        "\n"
        "class TestApi:\n"
        "    def setup_method(self):\n"
        "        self.api = Api()\n"
        "\n"
        "    def test_post(self, mocker):\n"
        '        mocker.patch.object(self.api, "_post")\n'
        "        assert self.api\n"
    )
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    assert [edge for edge in _mock_edges(conn) if "test_instance" in edge[0]] == [
        (
            "tests.test_instance.TestApi.test_post",
            "app.payments.Api._post",
            "low",
            '["mock_patch_by_name"]',
        ),
        (
            "tests.test_instance.TestApi.test_post",
            "app.refunds.Refunds._post",
            "low",
            '["mock_patch_by_name"]',
        ),
    ]


def test_run_scan_links_a_conftest_patch_on_an_instance_to_methods_of_that_name(
    tmp_path,
):
    _mocked_payments_app(tmp_path)
    (tmp_path / "tests" / "conftest.py").write_text(
        "import pytest\n"
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def quiet_api(api, mocker):\n"
        '    mocker.patch.object(api, "_post")\n'
    )
    (tmp_path / "tests" / "test_quiet.py").write_text(
        "def test_quiet(quiet_api):\n    assert quiet_api is None\n"
    )
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    assert (
        "tests.test_quiet.test_quiet",
        "app.payments.Api._post",
        "low",
        '["mock_patch_by_name"]',
    ) in _mock_edges(conn)


def test_refresh_index_keeps_mock_links_to_a_module_that_changed(tmp_path):
    _mocked_payments_app(tmp_path)
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    run_scan(conn, tmp_path, config)
    (tmp_path / "app" / "payments.py").write_text(
        "class Api:\n"
        "    def _post(self):\n"
        "        return 2\n"
        "\n"
        "\n"
        "def process_payment():\n"
        "    return Api()._post()\n"
    )

    refresh_index(conn, tmp_path, config)

    assert [edge[:2] for edge in _mock_edges(conn)] == [
        ("tests.test_checkout.test_checkout_mocked", "app.payments.process_payment"),
        ("tests.test_checkout.test_post_mocked", "app.payments.Api._post"),
    ]


def test_an_index_written_before_mock_links_existed_is_rebuilt_with_them(tmp_path):
    _mocked_payments_app(tmp_path)
    config = load_config(tmp_path)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, config)
    # What an index left by schema 6 code looks like: no mock links.
    conn.execute("DELETE FROM relationships WHERE relationship_type = 'mocks'")
    conn.execute("UPDATE index_metadata SET value = '6' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    conn = get_connection(tmp_path)
    ensure_fresh_index(conn, tmp_path, config)

    assert len(_mock_edges(conn)) == 2


def test_an_index_written_before_fixture_mock_links_existed_is_rebuilt_with_them(
    tmp_path,
):
    _mocked_payments_app(tmp_path)
    (tmp_path / "conftest.py").write_text(
        "import pytest\n"
        "\n"
        "from app.payments import Api\n"
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def quiet(mocker):\n"
        '    mocker.patch.object(Api, "_post")\n'
    )
    (tmp_path / "tests" / "test_quiet.py").write_text(
        "def test_quiet(quiet):\n    assert quiet is None\n"
    )
    config = load_config(tmp_path)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, config)
    # What an index left by schema 7 code looks like: no fixture mock links.
    conn.execute(
        """
        DELETE FROM relationships WHERE relationship_type = 'mocks'
          AND source_entity_id IN (
            SELECT id FROM symbols WHERE qualified_name = 'tests.test_quiet.test_quiet'
          )
        """
    )
    conn.execute("UPDATE index_metadata SET value = '7' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    conn = get_connection(tmp_path)
    ensure_fresh_index(conn, tmp_path, config)

    assert "tests.test_quiet.test_quiet" in [edge[0] for edge in _mock_edges(conn)]


def test_refresh_index_labels_new_files_with_the_given_registry(tmp_path):
    from project_mcp.plugins.descriptor import PluginDescriptor
    from project_mcp.plugins.registry import builtin_registry

    (tmp_path / "app.py").write_text("VALUE = 1\n")
    registry = builtin_registry()
    registry.register(
        PluginDescriptor(
            name="go", version="0.1.0", api_version=1, extensions={".go": "go"}
        )
    )
    config = load_config(tmp_path)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, config, registry=registry)

    (tmp_path / "main.go").write_text("package main\n")
    refresh_index(conn, tmp_path, config, registry=registry)

    assert dict(conn.execute("SELECT path, language FROM files")) == {
        "app.py": "python",
        "main.go": "go",
    }


class _UppercaseAnalyzer:
    """Each upper-case word is a symbol; `use NAME` imports NAME.toy."""

    analyzed: list[str] = []

    def is_test_file(self, path):
        return False

    def analyze(self, path, source):
        from project_mcp.plugins.analysis import FileAnalysis

        type(self).analyzed.append(path)
        module = Path(path).stem
        analysis = FileAnalysis()
        for word in source.split():
            if word.isupper():
                analysis.symbols.append(
                    {
                        "name": word,
                        "qualified_name": f"{module}.{word}",
                        "kind": "class",
                        "start_line": 1,
                        "end_line": 1,
                        "visibility": "public",
                    }
                )
        words = source.split()
        analysis.imports = [
            words[i + 1] for i, word in enumerate(words[:-1]) if word == "use"
        ]
        return analysis

    def resolve_import(self, importer, module):
        return [f"{module}.toy"]


def _uppercase_registry():
    from project_mcp.plugins.descriptor import PluginDescriptor
    from project_mcp.plugins.registry import builtin_registry

    registry = builtin_registry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.1.0",
            api_version=1,
            extensions={".toy": "toy"},
            analyzer=f"{__name__}:_UppercaseAnalyzer",
        )
    )
    return registry


def test_run_scan_hands_each_file_of_a_plugin_language_to_its_analyzer(tmp_path):
    (tmp_path / "shapes.toy").write_text("SQUARE CIRCLE\n")
    (tmp_path / "app.py").write_text("VALUE = 1\n")
    _UppercaseAnalyzer.analyzed = []
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path), registry=_uppercase_registry())

    assert _UppercaseAnalyzer.analyzed == ["shapes.toy"]
    assert sorted(
        conn.execute("SELECT qualified_name FROM symbols WHERE language = 'toy'")
    ) == [("shapes.CIRCLE",), ("shapes.SQUARE",)]


def test_refresh_index_links_a_plugin_import_once_its_target_file_is_added(tmp_path):
    (tmp_path / "square.toy").write_text("SQUARE use shapes\n")
    registry = _uppercase_registry()
    config = load_config(tmp_path)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, config, registry=registry)

    (tmp_path / "shapes.toy").write_text("SHAPE\n")
    refresh_index(conn, tmp_path, config, registry=registry)

    assert conn.execute(
        """
        SELECT source.path, target.path FROM relationships r
        JOIN files source ON source.id = r.source_entity_id
        JOIN files target ON target.id = r.target_entity_id
        WHERE r.relationship_type = 'imports' AND r.source_entity_type = 'file'
        """
    ).fetchall() == [("square.toy", "shapes.toy")]


class _TwoDialectAnalyzer(_UppercaseAnalyzer):
    """`use NAME` imports NAME in either dialect: NAME.toy or NAME.toyx."""

    def resolve_import(self, importer, module):
        return [f"{module}.toy", f"{module}.toyx"]


def test_refresh_index_relinks_every_language_of_a_plugin_when_a_file_is_added(
    tmp_path,
):
    from project_mcp.plugins.descriptor import PluginDescriptor
    from project_mcp.plugins.registry import builtin_registry

    registry = builtin_registry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.1.0",
            api_version=1,
            extensions={".toy": "toy", ".toyx": "toyx"},
            analyzer=f"{__name__}:_TwoDialectAnalyzer",
        )
    )
    (tmp_path / "square.toy").write_text("SQUARE use shapes\n")
    config = load_config(tmp_path)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, config, registry=registry)

    (tmp_path / "shapes.toyx").write_text("SHAPE\n")
    refresh_index(conn, tmp_path, config, registry=registry)

    assert conn.execute(
        """
        SELECT source.path, target.path FROM relationships r
        JOIN files source ON source.id = r.source_entity_id
        JOIN files target ON target.id = r.target_entity_id
        WHERE r.relationship_type = 'imports' AND r.source_entity_type = 'file'
        """
    ).fetchall() == [("square.toy", "shapes.toyx")]


def test_run_scan_without_a_registry_uses_the_projects_plugin_selection(tmp_path):
    (tmp_path / "lib.rs").write_text("pub fn run() {}\n")
    (tmp_path / "mcpctl.toml").write_text('[plugins]\ndisabled = ["rust"]\n')
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    assert conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 0
    assert conn.execute(
        "SELECT language FROM files WHERE path = 'lib.rs'"
    ).fetchone()[0] == "rust"


def test_scans_warn_while_no_language_plugin_is_active(tmp_path):
    from project_mcp.plugins.registry import PluginRegistry, builtin_registry

    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / "README.md").write_text("# demo\n")
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)

    run_scan(conn, tmp_path, config, registry=PluginRegistry())
    warned = get_index_status(conn).get("warnings")
    (tmp_path / "app.py").write_text("x = 2\n")
    refresh_index(conn, tmp_path, config, registry=builtin_registry())

    assert warned == ["no language plugins active; indexed 2 files at file level only"]
    assert "warnings" not in get_index_status(conn)


def test_scans_warn_about_frameworks_skipped_for_an_inactive_language(tmp_path):
    from project_mcp.plugins.registry import builtin_registry

    (tmp_path / "lib.rs").write_text("pub fn run() {}\n")
    registry = builtin_registry()
    registry.disable("python")
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path), registry=registry)

    assert get_index_status(conn)["warnings"] == [
        "django plugin skipped: it requires the python plugin, which is not active"
    ]


def test_scans_warn_about_plugins_that_failed_to_load(tmp_path):
    from project_mcp.plugins.descriptor import PluginDescriptor
    from project_mcp.plugins.registry import builtin_registry

    registry = builtin_registry()
    registry.register(
        PluginDescriptor(
            name="ghost",
            version="0.1.0",
            api_version=1,
            extensions={".ghost": "ghost"},
            analyzer="project_mcp.plugins.no_such_module:Ghost",
        )
    )
    (tmp_path / "a.ghost").write_text("boo\n")
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path), registry=registry)

    assert get_index_status(conn)["warnings"] == [
        "ghost plugin failed to load: No module named 'project_mcp.plugins.no_such_module'"
    ]


class _FailsOnSecondLook:
    def is_test_file(self, path):
        return False

    def analyze(self, path, source):
        from project_mcp.plugins.analysis import FileAnalysis

        if "v2" in source:
            raise RuntimeError("boom")
        return FileAnalysis(
            symbols=[
                {
                    "name": "a",
                    "qualified_name": "a",
                    "kind": "module",
                    "start_line": 1,
                    "end_line": 1,
                    "visibility": "public",
                }
            ]
        )

    def resolve_import(self, importer, spec):
        return []


def test_a_file_its_plugin_fails_on_keeps_no_symbols_from_an_earlier_analysis(tmp_path):
    from project_mcp.plugins.descriptor import PluginDescriptor
    from project_mcp.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.1.0",
            api_version=1,
            extensions={".toy": "toy"},
            analyzer=f"{__name__}:_FailsOnSecondLook",
        )
    )
    (tmp_path / "a.toy").write_text("v1\n")
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    run_scan(conn, tmp_path, config, registry=registry)

    (tmp_path / "a.toy").write_text("v2 now\n")
    refresh_index(conn, tmp_path, config, registry=registry)

    assert conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 0
    assert conn.execute(
        "SELECT analysis_status, analysis_error FROM files WHERE path = 'a.toy'"
    ).fetchone() == ("file_failed", "RuntimeError: boom")


def _python_registry(version):
    from dataclasses import replace

    from project_mcp.plugins.python.descriptor import DESCRIPTOR
    from project_mcp.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    registry.register(replace(DESCRIPTOR, version=version))
    return registry


def test_scan_reindexes_an_unchanged_file_whose_plugin_fingerprint_changed(tmp_path):
    (tmp_path / "app.py").write_text("def run():\n    pass\n")
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    run_scan(conn, tmp_path, config, registry=_python_registry("1.0.0"))

    run_scan(conn, tmp_path, config, registry=_python_registry("2.0.0"))

    assert conn.execute(
        "SELECT parser_version FROM files WHERE path = 'app.py'"
    ).fetchone()[0].startswith("python@2.0.0#")


def test_index_is_stale_when_a_plugin_fingerprint_changed(tmp_path):
    (tmp_path / "app.py").write_text("def run():\n    pass\n")
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    run_scan(conn, tmp_path, config, registry=_python_registry("1.0.0"))

    unchanged = get_index_status(conn, tmp_path, config, _python_registry("1.0.0"))
    bumped = get_index_status(conn, tmp_path, config, _python_registry("2.0.0"))

    assert (unchanged["status"], bumped["status"]) == ("fresh", "stale")


def test_disabling_a_plugin_drops_the_symbols_it_indexed(tmp_path):
    (tmp_path / "app.py").write_text("def run():\n    pass\n")
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    run_scan(conn, tmp_path, config, registry=_python_registry("1.0.0"))
    registry = _python_registry("1.0.0")
    registry.disable("python")

    run_scan(conn, tmp_path, config, registry=registry)

    assert conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 0
