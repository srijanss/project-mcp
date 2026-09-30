"""A symbol's definition with the surrounding facts an agent would otherwise Read for."""

from pathlib import Path

from project_mcp.tools.symbols import get_symbol_context


def describe_symbol(project_root: Path, qualified_name: str) -> dict:
    context = get_symbol_context(project_root, qualified_name)
    if not context["found"]:
        return context

    symbol = context["symbol"]
    lines = (Path(project_root) / symbol["file"]).read_text().splitlines()
    source = "\n".join(lines[symbol["start_line"] - 1 : symbol["end_line"]])
    return {**context, "source": source, "source_truncated": False}
