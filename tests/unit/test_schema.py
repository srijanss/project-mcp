import sqlite3

from project_mcp.schema import (
    CURRENT_SCHEMA_VERSION,
    REQUIRED_TABLES,
    get_schema_version,
    init_schema,
)


def test_init_schema_creates_all_required_tables():
    conn = sqlite3.connect(":memory:")

    init_schema(conn)

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert REQUIRED_TABLES <= tables


def test_init_schema_records_current_schema_version():
    conn = sqlite3.connect(":memory:")

    init_schema(conn)

    assert get_schema_version(conn) == CURRENT_SCHEMA_VERSION


def test_files_table_has_no_source_body_columns():
    conn = sqlite3.connect(":memory:")

    init_schema(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(files)").fetchall()}
    assert columns.isdisjoint({"content", "source", "body", "source_code"})


def test_init_schema_creates_git_facts_table_with_change_count_and_last_changed():
    conn = sqlite3.connect(":memory:")

    init_schema(conn)

    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(git_facts)").fetchall()
    }
    assert {"file_id", "change_count", "last_changed"} <= columns
