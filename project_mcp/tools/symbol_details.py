"""A symbol's definition with the surrounding facts an agent would otherwise Read for."""

from pathlib import Path

from project_mcp.db import get_connection
from project_mcp.tools.symbols import (
    find_symbol,
    get_dependencies,
    get_dependents,
    get_symbol_context,
)
from project_mcp.tools.tests import get_tests_for


MAX_SOURCE_LINES = 80


def _covering_tests(project_root: Path, qualified_name: str) -> list[dict]:
    """Tests for the symbol, else for the nearest enclosing module or class."""
    parts = qualified_name.split(".")
    for length in range(len(parts), 0, -1):
        candidate = ".".join(parts[:length])
        rows = get_tests_for(project_root, candidate)
        if rows:
            scope = "symbol" if candidate == qualified_name else "module"
            return [{**row, "scope": scope} for row in rows]
    return []


def _in_test_files(project_root: Path, qualified_names: list[str]) -> set[str]:
    if not qualified_names:
        return set()
    conn = get_connection(project_root)
    try:
        marks = ",".join("?" * len(qualified_names))
        rows = conn.execute(
            f"""
            SELECT s.qualified_name FROM symbols s
            JOIN files f ON f.id = s.file_id
            WHERE f.file_kind = 'test' AND s.qualified_name IN ({marks})
            """,
            qualified_names,
        ).fetchall()
    finally:
        conn.close()
    return {row[0] for row in rows}


def _callers(project_root: Path, qualified_name: str) -> list[dict]:
    """Direct callers, leaving tests to the separate `tests` list."""
    rows = [
        row
        for row in get_dependents(project_root, qualified_name)
        if row["relationship_type"] == "calls"
    ]
    in_tests = _in_test_files(project_root, [row["source"] for row in rows])
    return [
        {"symbol": row["source"], "confidence": row["confidence"]}
        for row in rows
        if row["source"] not in in_tests
    ]


def _resolve(project_root: Path, name: str) -> dict:
    """Look `name` up exactly, else as a short name if it is unambiguous."""
    context = get_symbol_context(project_root, name)
    if context["found"]:
        return context
    suffix = f".{name}"
    matches = {
        row["qualified_name"]
        for row in find_symbol(project_root, name)
        if row["name"] == name or row["qualified_name"].endswith(suffix)
    }
    if len(matches) == 1:
        return get_symbol_context(project_root, matches.pop())
    return context


def describe_symbol(project_root: Path, qualified_name: str) -> dict:
    context = _resolve(project_root, qualified_name)
    if not context["found"]:
        return context

    symbol = context["symbol"]
    qualified_name = symbol["qualified_name"]
    lines = (Path(project_root) / symbol["file"]).read_text().splitlines()
    definition = lines[symbol["start_line"] - 1 : symbol["end_line"]]
    return {
        **context,
        "source": "\n".join(definition[:MAX_SOURCE_LINES]),
        "source_truncated": len(definition) > MAX_SOURCE_LINES,
        "source_total_lines": len(definition),
        "callers": _callers(project_root, qualified_name),
        "callees": [
            {"symbol": row["target"], "confidence": row["confidence"]}
            for row in get_dependencies(project_root, qualified_name)
            if row["relationship_type"] == "calls"
        ],
        "tests": _covering_tests(project_root, qualified_name),
    }
