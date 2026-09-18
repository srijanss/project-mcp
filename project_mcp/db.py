import sqlite3
from pathlib import Path

from project_mcp.schema import (
    CURRENT_SCHEMA_VERSION,
    REQUIRED_TABLES,
    get_schema_version,
    init_schema,
)


def get_connection(project_root: Path) -> sqlite3.Connection:
    project_root = Path(project_root)
    db_path = project_root / ".project-mcp" / "index.db"
    conn = sqlite3.connect(db_path)
    init_schema(conn)
    _invalidate_if_stale(conn)
    return conn


def _invalidate_if_stale(conn: sqlite3.Connection) -> None:
    version = get_schema_version(conn)
    if version is None or version == CURRENT_SCHEMA_VERSION:
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    for table in REQUIRED_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()
    init_schema(conn)
