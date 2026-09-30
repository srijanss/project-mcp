from project_mcp.db import get_connection
from project_mcp.schema import CURRENT_SCHEMA_VERSION, REQUIRED_TABLES


def test_get_connection_creates_index_db_file(tmp_path):
    (tmp_path / ".project-mcp").mkdir()

    get_connection(tmp_path)

    assert (tmp_path / ".project-mcp" / "index.db").exists()


def test_get_connection_creates_project_mcp_dir_when_missing(tmp_path):
    get_connection(tmp_path)

    assert (tmp_path / ".project-mcp" / "index.db").exists()


def test_get_connection_reopening_preserves_data(tmp_path):
    (tmp_path / ".project-mcp").mkdir()

    conn = get_connection(tmp_path)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()

    reopened = get_connection(tmp_path)
    rows = reopened.execute("SELECT x FROM t").fetchall()
    reopened.close()

    assert rows == [(1,)]


def test_get_connection_after_deleting_db_file_recreates_clean_db(tmp_path):
    (tmp_path / ".project-mcp").mkdir()

    conn = get_connection(tmp_path)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    conn.close()

    (tmp_path / ".project-mcp" / "index.db").unlink()

    recreated = get_connection(tmp_path)
    tables = {
        row[0]
        for row in recreated.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    recreated.close()

    assert "t" not in tables


def test_get_connection_auto_initializes_schema_tables(tmp_path):
    (tmp_path / ".project-mcp").mkdir()

    conn = get_connection(tmp_path)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    assert REQUIRED_TABLES <= tables


def test_get_connection_invalidates_stale_schema_version(tmp_path):
    (tmp_path / ".project-mcp").mkdir()

    conn = get_connection(tmp_path)
    conn.execute(
        "INSERT INTO projects (root_path, created_at) VALUES ('/tmp/x', '2026-01-01')"
    )
    conn.execute("INSERT INTO files (project_id, path) VALUES (1, 'stale.py')")
    conn.execute("UPDATE index_metadata SET value = '0' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    reopened = get_connection(tmp_path)
    file_rows = reopened.execute("SELECT * FROM files").fetchall()
    version = reopened.execute(
        "SELECT value FROM index_metadata WHERE key = 'schema_version'"
    ).fetchone()
    reopened.close()

    assert file_rows == []
    assert version == (str(CURRENT_SCHEMA_VERSION),)


def test_get_connection_rebuilds_index_written_before_cross_module_edges(tmp_path):
    """Version 1 indexes lack cross-module calls and attribute references.

    Incremental refresh only re-indexes changed files, so without a rebuild an
    upgraded install would keep a partially old graph while reporting 'fresh'.
    """
    (tmp_path / ".project-mcp").mkdir()

    conn = get_connection(tmp_path)
    conn.execute(
        "INSERT INTO projects (root_path, created_at) VALUES ('/tmp/x', '2026-01-01')"
    )
    conn.execute("INSERT INTO files (project_id, path) VALUES (1, 'old.py')")
    conn.execute("UPDATE index_metadata SET value = '1' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    reopened = get_connection(tmp_path)
    file_rows = reopened.execute("SELECT * FROM files").fetchall()
    reopened.close()

    assert file_rows == []


def test_get_connection_reads_while_another_connection_holds_the_write_lock(tmp_path):
    """A second session re-indexing must not make status/read tools fail.

    Opening a connection on an already-initialised index used to write
    (schema_version INSERT OR IGNORE), so it queued behind the indexer's write
    lock and surfaced as "database is locked".
    """
    writer = get_connection(tmp_path)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute(
        "INSERT OR REPLACE INTO index_metadata (key, value) VALUES ('index_status', 'indexing')"
    )

    reader = get_connection(tmp_path)
    try:
        rows = reader.execute(
            "SELECT value FROM index_metadata WHERE key = 'schema_version'"
        ).fetchall()
    finally:
        reader.close()
        writer.rollback()
        writer.close()

    assert rows == [(str(CURRENT_SCHEMA_VERSION),)]
