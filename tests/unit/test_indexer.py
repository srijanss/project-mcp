from project_mcp.db import get_connection
from project_mcp.indexer import (
    begin_index,
    get_index_status,
    mark_index_complete,
    remove_file,
    upsert_file,
)


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
