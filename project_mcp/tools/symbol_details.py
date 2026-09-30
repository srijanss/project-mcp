"""A symbol's definition with the surrounding facts an agent would otherwise Read for."""

from pathlib import Path

from project_mcp.tools.symbols import (
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


def describe_symbol(project_root: Path, qualified_name: str) -> dict:
    context = get_symbol_context(project_root, qualified_name)
    if not context["found"]:
        return context

    symbol = context["symbol"]
    lines = (Path(project_root) / symbol["file"]).read_text().splitlines()
    definition = lines[symbol["start_line"] - 1 : symbol["end_line"]]
    return {
        **context,
        "source": "\n".join(definition[:MAX_SOURCE_LINES]),
        "source_truncated": len(definition) > MAX_SOURCE_LINES,
        "source_total_lines": len(definition),
        "callers": [
            {"symbol": row["source"], "confidence": row["confidence"]}
            for row in get_dependents(project_root, qualified_name)
            if row["relationship_type"] == "calls"
        ],
        "callees": [
            {"symbol": row["target"], "confidence": row["confidence"]}
            for row in get_dependencies(project_root, qualified_name)
            if row["relationship_type"] == "calls"
        ],
        "tests": _covering_tests(project_root, qualified_name),
    }
