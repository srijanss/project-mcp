import pytest

from project_mcp.db import get_connection
from tests.golden import FIXTURES, dump_snapshot, load_snapshot, touch_indexed_files


def _insert(conn, table, **values):
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    cursor = conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    )
    return cursor.lastrowid


def test_dump_snapshot_names_rows_by_path_and_symbol_instead_of_ids(tmp_path):
    conn = get_connection(tmp_path)
    project_id = _insert(
        conn, "projects", root_path=str(tmp_path), created_at="2026-01-01"
    )
    file_id = _insert(
        conn,
        "files",
        project_id=project_id,
        path="app/models.py",
        language="python",
        file_kind="source",
        size=10,
        mtime_ns=123,
        indexed_at="2026-01-01",
    )
    base_id = _insert(
        conn,
        "symbols",
        file_id=file_id,
        name="Base",
        qualified_name="app.models.Base",
        kind="class",
        language="python",
        start_line=1,
        end_line=2,
        visibility="public",
        metadata_json=None,
    )
    child_id = _insert(
        conn,
        "symbols",
        file_id=file_id,
        name="Child",
        qualified_name="app.models.Child",
        kind="class",
        language="python",
        start_line=4,
        end_line=5,
        visibility="public",
        metadata_json='{"bases": ["Base"]}',
    )
    _insert(
        conn,
        "relationships",
        source_entity_type="symbol",
        source_entity_id=child_id,
        target_entity_type="symbol",
        target_entity_id=base_id,
        relationship_type="inherits",
        confidence="high",
        evidence_json='{"line": 4}',
    )
    _insert(
        conn,
        "tests",
        symbol_id=child_id,
        file_id=file_id,
        test_kind="unit",
        framework="pytest",
        metadata_json=None,
    )
    _insert(
        conn,
        "dependencies",
        project_id=project_id,
        name="django",
        ecosystem="python",
        declared_version=">=5",
        resolved_version=None,
        source_file="pyproject.toml",
        scope="runtime",
        metadata_json=None,
    )

    assert dump_snapshot(conn) == {
        "files": [
            {"path": "app/models.py", "language": "python", "file_kind": "source"}
        ],
        "symbols": [
            {
                "path": "app/models.py",
                "name": "Base",
                "qualified_name": "app.models.Base",
                "kind": "class",
                "language": "python",
                "start_line": 1,
                "end_line": 2,
                "visibility": "public",
                "metadata": None,
            },
            {
                "path": "app/models.py",
                "name": "Child",
                "qualified_name": "app.models.Child",
                "kind": "class",
                "language": "python",
                "start_line": 4,
                "end_line": 5,
                "visibility": "public",
                "metadata": {"bases": ["Base"]},
            },
        ],
        "relationships": [
            {
                "source": {"symbol": "app.models.Child", "path": "app/models.py"},
                "target": {"symbol": "app.models.Base", "path": "app/models.py"},
                "relationship_type": "inherits",
                "confidence": "high",
                "evidence": {"line": 4},
            }
        ],
        "tests": [
            {
                "path": "app/models.py",
                "symbol": "app.models.Child",
                "test_kind": "unit",
                "framework": "pytest",
                "metadata": None,
            }
        ],
        "dependencies": [
            {
                "name": "django",
                "ecosystem": "python",
                "declared_version": ">=5",
                "resolved_version": None,
                "source_file": "pyproject.toml",
                "scope": "runtime",
                "metadata": None,
            }
        ],
    }


def test_dump_snapshot_names_file_relationship_ends_by_path(tmp_path):
    conn = get_connection(tmp_path)
    project_id = _insert(
        conn, "projects", root_path=str(tmp_path), created_at="2026-01-01"
    )
    importer_id, imported_id = (
        _insert(conn, "files", project_id=project_id, path=path)
        for path in ("app/views.py", "app/models.py")
    )
    _insert(
        conn,
        "relationships",
        source_entity_type="file",
        source_entity_id=importer_id,
        target_entity_type="file",
        target_entity_id=imported_id,
        relationship_type="imports",
        confidence="high",
    )

    assert dump_snapshot(conn)["relationships"] == [
        {
            "source": {"file": "app/views.py"},
            "target": {"file": "app/models.py"},
            "relationship_type": "imports",
            "confidence": "high",
            "evidence": None,
        }
    ]


@pytest.mark.parametrize("name", ["python", "javascript", "react", "rust"])
def test_every_fixture_has_a_committed_snapshot(name):
    assert FIXTURES[name].is_dir()
    assert set(load_snapshot(name)) == {
        "files",
        "symbols",
        "relationships",
        "tests",
        "dependencies",
    }


def test_touch_indexed_files_moves_mtime_past_the_indexed_value(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("VALUE = 1\n")
    indexed_mtime = source.stat().st_mtime_ns
    conn = get_connection(tmp_path)
    project_id = _insert(
        conn, "projects", root_path=str(tmp_path), created_at="2026-01-01"
    )
    _insert(conn, "files", project_id=project_id, path="app.py", mtime_ns=indexed_mtime)

    touch_indexed_files(conn, tmp_path)

    assert source.stat().st_mtime_ns != indexed_mtime
    assert source.read_text() == "VALUE = 1\n"
