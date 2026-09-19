import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import (
    begin_index,
    ensure_fresh_index,
    get_index_status,
    mark_index_complete,
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
    assert status["schema_version"] == 1


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
