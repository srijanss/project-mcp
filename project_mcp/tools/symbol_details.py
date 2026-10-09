"""A symbol's definition with the surrounding facts an agent would otherwise Read for."""

import difflib
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
MAX_SUGGESTIONS = 5


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


_OUTLINE_GROUPS = {"field": "fields", "method": "methods", "class": "classes"}


def _outline(project_root: Path, symbol: dict) -> dict:
    """A class's direct members, one line per kind: `name` for fields, `name:line` else."""
    prefix = f"{symbol['qualified_name']}."
    conn = get_connection(project_root)
    try:
        rows = conn.execute(
            """
            SELECT s.name, s.kind, s.start_line FROM symbols s
            JOIN files f ON f.id = s.file_id
            WHERE f.path = ?
              AND substr(s.qualified_name, 1, ?) = ?
              AND instr(substr(s.qualified_name, ? + 1), '.') = 0
            ORDER BY s.start_line
            """,
            (symbol["file"], len(prefix), prefix, len(prefix)),
        ).fetchall()
    finally:
        conn.close()
    groups: dict[str, list[str]] = {}
    for name, kind, line in rows:
        # Fields are listed by name; everything else carries its start line.
        groups.setdefault(_OUTLINE_GROUPS.get(kind, f"{kind}s"), []).append(
            name if kind == "field" else f"{name}:{line}"
        )
    return {group: ", ".join(entries) for group, entries in groups.items()}


def _similar_names(project_root: Path, short: str) -> list[str]:
    """Qualified names whose own name is close to `short`, e.g. a one-letter typo."""
    conn = get_connection(project_root)
    try:
        rows = conn.execute(
            "SELECT name, qualified_name FROM symbols WHERE kind != 'module'"
        ).fetchall()
    finally:
        conn.close()
    by_name: dict[str, list[str]] = {}
    for name, qualified_name in rows:
        by_name.setdefault(name.lower(), []).append(qualified_name)
    close = difflib.get_close_matches(short.lower(), by_name, n=MAX_SUGGESTIONS)
    return [qn for name in close for qn in sorted(by_name[name])]


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
    if matches:
        return {**context, "candidates": sorted(matches)}
    # Likely a mistyped path: offer the nearest matches for its last segment.
    short = name.rsplit(".", 1)[-1]
    nearest = [
        row["qualified_name"]
        for row in find_symbol(project_root, short, limit=MAX_SUGGESTIONS * 10)
        if short.lower() in row["name"].lower()  # not merely inside a longer path
    ]
    if len(nearest) < MAX_SUGGESTIONS:
        nearest += [
            qn for qn in _similar_names(project_root, short) if qn not in nearest
        ]
    nearest = nearest[:MAX_SUGGESTIONS]
    if nearest:
        return {**context, "suggestions": nearest}
    return context


def describe_symbol(project_root: Path, qualified_name: str) -> dict:
    context = _resolve(project_root, qualified_name)
    if not context["found"]:
        return context

    symbol = context["symbol"]
    qualified_name = symbol["qualified_name"]
    try:
        # Replace invalid bytes as the indexer does, so its line numbers still match.
        lines = (Path(project_root) / symbol["file"]).read_text(errors="replace").splitlines()
    except OSError as exc:  # e.g. the file was deleted after indexing
        source = {
            "source": None,
            "source_error": type(exc).__name__,
            "source_truncated": False,
            "source_total_lines": 0,
        }
    else:
        definition = lines[symbol["start_line"] - 1 : symbol["end_line"]]
        source = {
            "source": "\n".join(definition[:MAX_SOURCE_LINES]),
            "source_truncated": len(definition) > MAX_SOURCE_LINES,
            "source_total_lines": len(definition),
        }
    # A cut-off class body ends mid-method; its member list is the useful overview.
    outline = (
        {"outline": _outline(project_root, symbol)}
        if symbol["kind"] == "class" and source["source_truncated"]
        else {}
    )
    dependencies = get_dependencies(project_root, qualified_name)

    def linked(relationship_type: str) -> list[dict]:
        return [
            {"symbol": row["target"], "confidence": row["confidence"]}
            for row in dependencies
            if row["relationship_type"] == relationship_type
        ]

    return {
        **context,
        **source,
        **outline,
        "callers": _callers(project_root, qualified_name),
        "callees": linked("calls"),
        "references": linked("references"),
        "tests": _covering_tests(project_root, qualified_name),
    }
