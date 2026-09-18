from project_mcp.db import get_connection


def test_get_connection_creates_index_db_file(tmp_path):
    (tmp_path / ".project-mcp").mkdir()

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
    tables = recreated.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    recreated.close()

    assert tables == []
