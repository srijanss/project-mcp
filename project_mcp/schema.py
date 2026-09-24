import sqlite3

# Bumped whenever the *meaning* of indexed data changes, not just its tables:
# get_connection() discards an index written under an older version, so an
# upgrade rebuilds it instead of mixing old and new relationship kinds.
# 2: cross-module calls and attribute references (fields) are now indexed.
# 3: module constants and references to them are now indexed, and
#    `from x import a as b` aliases resolve for calls and constants, and
#    `mod.func()` calls resolve through `import mod` / `import mod as m`.
CURRENT_SCHEMA_VERSION = 3

REQUIRED_TABLES = {
    "projects",
    "files",
    "symbols",
    "relationships",
    "dependencies",
    "tests",
    "architecture_facts",
    "legacy_signals",
    "index_metadata",
    "git_facts",
}

_TABLE_DDL = [
    """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        root_path TEXT NOT NULL UNIQUE,
        name TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        language TEXT,
        file_kind TEXT,
        size INTEGER,
        mtime_ns INTEGER,
        content_hash TEXT,
        parser_version TEXT,
        indexed_at TEXT,
        UNIQUE(project_id, path)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS symbols (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        qualified_name TEXT,
        kind TEXT,
        language TEXT,
        start_line INTEGER,
        end_line INTEGER,
        visibility TEXT,
        metadata_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_entity_type TEXT NOT NULL,
        source_entity_id INTEGER NOT NULL,
        target_entity_type TEXT NOT NULL,
        target_entity_id INTEGER NOT NULL,
        relationship_type TEXT NOT NULL,
        confidence TEXT,
        evidence_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dependencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        ecosystem TEXT NOT NULL,
        declared_version TEXT,
        resolved_version TEXT,
        source_file TEXT,
        scope TEXT,
        metadata_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol_id INTEGER REFERENCES symbols(id) ON DELETE CASCADE,
        file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
        test_kind TEXT,
        framework TEXT,
        metadata_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS architecture_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object TEXT NOT NULL,
        origin TEXT NOT NULL,
        source TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS legacy_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target TEXT NOT NULL,
        signal TEXT NOT NULL,
        severity TEXT,
        confidence TEXT,
        evidence TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS index_metadata (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS git_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
        change_count INTEGER,
        last_changed TEXT,
        computed_at TEXT,
        UNIQUE(file_id)
    )
    """,
]


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    for ddl in _TABLE_DDL:
        conn.execute(ddl)
    conn.execute(
        "INSERT OR IGNORE INTO index_metadata (key, value) VALUES ('schema_version', ?)",
        (str(CURRENT_SCHEMA_VERSION),),
    )
    conn.commit()


def get_schema_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT value FROM index_metadata WHERE key = 'schema_version'"
    ).fetchone()
    return int(row[0]) if row else None
