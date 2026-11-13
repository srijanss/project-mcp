import sqlite3
from pathlib import Path

from project_mcp.schema import (
    CURRENT_SCHEMA_VERSION,
    REQUIRED_TABLES,
    get_schema_version,
    init_schema,
)


# Another session's full re-index can hold the write lock for many seconds.
BUSY_TIMEOUT_SECONDS = 30


def get_connection(project_root: Path) -> sqlite3.Connection:
    project_root = Path(project_root)
    project_mcp_dir = project_root / ".project-mcp"
    project_mcp_dir.mkdir(exist_ok=True)
    db_path = project_mcp_dir / "index.db"
    conn = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_SECONDS)
    _enable_wal(conn)
    init_schema(conn)
    _invalidate_if_stale(conn)
    return conn


def _enable_wal(conn: sqlite3.Connection) -> None:
    """Switch the index to WAL so readers keep reading while a re-index writes.

    Converting an older rollback-journal index needs an exclusive lock. When
    another session holds a lock, skip it without waiting: this connection
    works in the old mode and a later connection converts the index.
    """
    conn.execute("PRAGMA busy_timeout = 0")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError as error:
        if error.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise
    finally:
        conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_SECONDS * 1000)}")


def _invalidate_if_stale(conn: sqlite3.Connection) -> None:
    version = get_schema_version(conn)
    if version is None or version == CURRENT_SCHEMA_VERSION:
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    for table in REQUIRED_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()
    init_schema(conn)
