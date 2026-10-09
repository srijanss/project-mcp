"""What a react source file imports and renders, read from a tree-sitter syntax tree."""
import re
from pathlib import Path

from project_mcp.plugins import treesitter
from project_mcp.plugins.javascript.tree_parser import (
    _SCOPE_TYPES,
    _declared_function,
    _local_names,
)

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
_DEFAULT_KEYWORD = re.compile(r"export\s+default\b")


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
                    if item.type != "import_specifier" or item.text.startswith("type "):
                        continue
                    identifiers = [child.text for child in item.children]
                    names[identifiers[-1]] = (specifier, identifiers[0])
    return names


def default_export_name(source: str, grammar: str) -> str | None:
    """The local name a file exports as its default, if statically visible.

    A wrapper call such as `memo(Badge)` or `connect(a)(Card)` exports what it wraps.
    """
    for statement in treesitter.parse(source, grammar).children:
        if statement.type != "export_statement":
            continue
        value = statement.field("value")
        if value is not None:
            return _wrapped_name(value)
        declaration = statement.field("declaration")
        if declaration is not None and _DEFAULT_KEYWORD.match(statement.text):
            name = declaration.field("name")
            return name.text if name is not None else None
        aliased = _aliased_default(statement)
        if aliased is not None:
            return aliased
    return None


def _aliased_default(statement) -> str | None:
    """The local name in `export { Name as default }`; re-exports from another module don't count."""
    clause = next((c for c in statement.children if c.type == "export_clause"), None)
    if clause is None or statement.field("source") is not None:
        return None
    for specifier in clause.children:
        alias = specifier.field("alias")
        if alias is not None and alias.text == "default":
            return specifier.field("name").text
    return None


def _wrapped_name(node) -> str | None:
    """The identifier or named function at the core of nested wrapper calls, by their first arguments."""
    while node.type == "call_expression":
        arguments = [a for a in node.field("arguments").children if a.type != "comment"]
        if not arguments:
            return None
        node = arguments[0]
    if node.type == "function_expression":
        name = node.field("name")
        return name.text if name is not None else None
    return node.text if node.type == "identifier" else None


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


def shadowed_tags(source: str, grammar: str, functions: bool = False) -> set[tuple[str, int]]:
    """The (name, line) of each JSX tag naming a parameter or variable of an enclosing function.

    Functions declared in an enclosing function are symbols of their own, so
    they only count as bindings when `functions` is set.
    """
    shadowed: set[tuple[str, int]] = set()

    def visit(node, bound: frozenset[str]) -> None:
        if node.type in _SCOPE_TYPES:
            bound = bound | set(_local_names(node))
            if functions and node.field("body") is not None:
                bound = bound | set(_function_names(node.field("body")))
        if node.type in _JSX_TAGS:
            name = node.field("name")
            if name is not None and name.type == "identifier" and name.text in bound:
                shadowed.add((name.text, node.start_line))
        for child in node.children:
            visit(child, bound)

    visit(treesitter.parse(source, grammar), frozenset())
    return shadowed


def _function_names(body) -> list[str]:
    """The functions declared directly in `body`, not in functions nested in it."""
    names = []
    for child in body.children:
        if child.type == "function_declaration":
            names.append(child.field("name").text)
        elif child.type in _SCOPE_TYPES:
            continue
        else:
            if child.type == "variable_declarator" and _declared_function(child) is not None:
                names.append(child.field("name").text)
            names += _function_names(child)
    return names


def export_aliases(source: str, grammar: str) -> dict[str, str]:
    """The local name behind each export an export list renames, by exported name.

    Re-exports from another module and `as default` aliases don't count.
    """
    aliases = {}
    for statement in treesitter.parse(source, grammar).children:
        clause = next((c for c in statement.children if c.type == "export_clause"), None)
        if statement.type != "export_statement" or clause is None or statement.field("source"):
            continue
        for specifier in clause.children:
            alias = specifier.field("alias")
            if alias is not None and alias.text != "default":
                aliases[alias.text] = specifier.field("name").text
    return aliases
