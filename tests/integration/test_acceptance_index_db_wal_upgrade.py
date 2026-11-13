import sqlite3
import time

from project_mcp.db import get_connection


def _legacy_index(tmp_path):
    """An index written before WAL: current schema, rollback journal, some data."""
    conn = get_connection(tmp_path)
    conn.execute("INSERT OR REPLACE INTO index_metadata (key, value) VALUES ('index_status', 'fresh')")
    conn.commit()
    conn.close()
    legacy = sqlite3.connect(tmp_path / ".project-mcp" / "index.db")
    assert legacy.execute("PRAGMA journal_mode=DELETE").fetchone() == ("delete",)
    legacy.close()


def _status_and_mode(conn):
    status = conn.execute("SELECT value FROM index_metadata WHERE key = 'index_status'").fetchall()
    return status, conn.execute("PRAGMA journal_mode").fetchone()[0]


def test_an_existing_index_is_upgraded_to_wal_without_losing_data(tmp_path):
    _legacy_index(tmp_path)

    conn = get_connection(tmp_path)
    try:
        assert _status_and_mode(conn) == ([("fresh",)], "wal")
    finally:
        conn.close()


def test_a_reader_from_an_older_session_does_not_stall_or_break_the_upgrade(tmp_path):
    _legacy_index(tmp_path)
    old_session = sqlite3.connect(tmp_path / ".project-mcp" / "index.db", isolation_level=None)
    old_session.execute("BEGIN")
    old_session.execute("SELECT * FROM index_metadata").fetchall()

    try:
        started = time.monotonic()
        conn = get_connection(tmp_path)
        waited = time.monotonic() - started
        try:
            assert _status_and_mode(conn) == ([("fresh",)], "delete")
        finally:
            conn.close()
    finally:
        old_session.execute("COMMIT")
        old_session.close()

    assert waited < 5

    conn = get_connection(tmp_path)
    try:
        assert _status_and_mode(conn) == ([("fresh",)], "wal")
    finally:
        conn.close()
