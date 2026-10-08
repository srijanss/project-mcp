"""What a react source file imports and renders, read from a tree-sitter syntax tree."""
from pathlib import Path

from project_mcp.plugins import treesitter

# file suffix -> the tree-sitter grammar that parses it
_GRAMMARS = {
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "tsx",
    ".ts": "typescript",
    ".tsx": "tsx",
}
_JSX_TAGS = {"jsx_opening_element", "jsx_self_closing_element"}


def grammar_for(path: str) -> str:
    return _GRAMMARS[Path(path).suffix]


def imported_names(source: str, grammar: str) -> dict[str, tuple[str, str]]:
    """The (module specifier, imported name) behind each local name a file imports.

    The same result as `usages.imported_names`, read from the syntax tree.
    """
    names: dict[str, tuple[str, str]] = {}
    for statement in treesitter.parse(source, grammar).children:
        clause = next((c for c in statement.children if c.type == "import_clause"), None)
        if statement.type != "import_statement" or clause is None:
            continue
        if statement.text.startswith("import type "):
            continue
        specifier = statement.field("source").text[1:-1]
        for part in clause.children:
            if part.type == "identifier":
                names[part.text] = (specifier, "default")
            elif part.type == "named_imports":
                for item in part.children:
                    if item.text.startswith("type "):
                        continue
                    identifiers = [child.text for child in item.children]
                    names[identifiers[-1]] = (specifier, identifiers[0])
    return names


def jsx_tags(source: str, grammar: str) -> list[tuple[str, int]]:
    """Each capitalised JSX tag name with the line it opens on, in source order."""
    tags: list[tuple[str, int]] = []

    def visit(node) -> None:
        if node.type in _JSX_TAGS:
            name = node.field("name")
            if name is not None and name.type == "identifier" and name.text[:1].isupper():
                tags.append((name.text, node.start_line))
        for child in node.children:
            visit(child)

    visit(treesitter.parse(source, grammar))
    return tags
