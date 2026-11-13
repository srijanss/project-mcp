import project_mcp.db as db
from project_mcp.db import get_connection


def test_a_reader_is_not_blocked_by_a_reindex_holding_the_exclusive_write_lock(tmp_path, monkeypatch):
    """Read-only tool calls from another session must not fail with "database is locked".

    Without WAL, a writer holding the exclusive lock (as a re-index does while
    committing) blocks every reader until the busy timeout expires.
    """
    writer = get_connection(tmp_path)
    writer.execute("INSERT OR REPLACE INTO index_metadata (key, value) VALUES ('index_status', 'fresh')")
    writer.commit()
    writer.execute("BEGIN EXCLUSIVE")
    writer.execute("INSERT OR REPLACE INTO index_metadata (key, value) VALUES ('index_status', 'indexing')")

    monkeypatch.setattr(db, "BUSY_TIMEOUT_SECONDS", 0.2)
    reader = get_connection(tmp_path)
    try:
        during = reader.execute("SELECT value FROM index_metadata WHERE key = 'index_status'").fetchall()
        writer.commit()
        after = reader.execute("SELECT value FROM index_metadata WHERE key = 'index_status'").fetchall()
    finally:
        reader.close()
        writer.close()

    assert during == [("fresh",)]
    assert after == [("indexing",)]
