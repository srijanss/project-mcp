import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.schema import CURRENT_SCHEMA_VERSION
from project_mcp.indexer import (
    begin_index,
    ensure_fresh_index,
    get_index_status,
    index_legacy_signals,
    index_python_attribute_relationships,
    mark_index_complete,
    refresh_index,
    remove_file,
    run_scan,
    upsert_file,
)

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
    import project_mcp.indexer as indexer_module

    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    calls = []
    original_extract_imports = indexer_module.extract_imports

    def spy(path, source):
        calls.append(path)
        return original_extract_imports(path, source)

    monkeypatch.setattr(indexer_module, "extract_imports", spy)

    run_scan(conn, project_root, config)

    assert calls == []


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


def test_index_python_attribute_relationships_looks_up_symbols_once_per_file(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    fields = [f"field_{i}" for i in range(30)]
    source = (
        "class Payment:\n"
        + "".join(f"    {name} = {i}\n" for i, name in enumerate(fields))
        + "\n"
        + "    def run(self):\n"
        + "".join(f"        self.{name}\n" for name in fields)
    )
    (project_root / "app" / "payment.py").write_text(source)
    run_scan(conn, project_root, config)
    file_id = conn.execute(
        "SELECT id FROM files WHERE path = 'app/payment.py'"
    ).fetchone()[0]
    references = [
        {
            "referrer": "app.payment.Payment.run",
            "class": "app.payment.Payment",
            "attribute": name,
            "line": 1,
        }
        for name in fields
    ]

    statements = []
    conn.set_trace_callback(statements.append)
    index_python_attribute_relationships(conn, file_id, references)
    conn.set_trace_callback(None)

    symbol_lookups = [s for s in statements if "FROM symbols" in s]
    assert len(symbol_lookups) <= 1


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
    fixture_root = Path(__file__).parent.parent / "fixtures" / "git" / "churn-fixture"
    project_root = tmp_path / "churn-fixture"
    shutil.copytree(fixture_root, project_root)
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


def test_run_scan_calls_get_files_changed_together_exactly_once_per_indexed_file(tmp_path):
    """Characterization test: temporal-coupling detection runs one git subprocess
    call (via get_files_changed_together) per indexed file — no more, no less.
    Locks in the current linear-cost design so a future change can't silently
    make it worse (e.g. calling it per-symbol) without a test noticing."""
    from unittest.mock import patch

    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "a.py").write_text("x = 1\n")
    (project_root / "app" / "b.py").write_text("y = 1\n")

    conn = get_connection(project_root)
    config = load_config(project_root)

    with patch(
        "project_mcp.indexer.get_files_changed_together", return_value=[]
    ) as mock_coupling:
        run_scan(conn, project_root, config)

    file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    assert mock_coupling.call_count == file_count


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
