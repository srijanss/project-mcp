import shutil
from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import (
    begin_index,
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

    assert len(file_queries) <= 1


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
