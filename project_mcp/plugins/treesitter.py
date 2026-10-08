"""Shared tree-sitter parsing for plugins (needs the optional 'treesitter' extra).

Only plugin code imports this module; core never does. tree-sitter itself is
imported on use, so a plugin can import this module and ask `missing()`
whether to fall back to its regex parser.
"""

import importlib

# grammar name -> (module, function returning the language pointer)
GRAMMARS = {
    "javascript": ("tree_sitter_javascript", "language"),
    "rust": ("tree_sitter_rust", "language"),
}


class Node:
    def __init__(self, node):
        self._node = node

    @property
    def type(self) -> str:
        return self._node.type

    @property
    def start_line(self) -> int:
        return self._node.start_point.row + 1

    @property
    def end_line(self) -> int:
        # A node that ends with a newline stops at column 0 of the next line.
        row, column = self._node.end_point
        if column == 0 and row > self._node.start_point.row:
            return row
        return row + 1

    @property
    def text(self) -> str:
        return self._node.text.decode()

    @property
    def children(self) -> list["Node"]:
        return [Node(child) for child in self._node.named_children]

    def field(self, name: str) -> "Node | None":
        child = self._node.child_by_field_name(name)
        return Node(child) if child is not None else None


def missing(grammar: str) -> str | None:
    """Why `grammar` cannot be parsed here (an uninstalled module), or None."""
    for module in ("tree_sitter", GRAMMARS[grammar][0]):
        try:
            importlib.import_module(module)
        except ImportError as exc:
            return f"{module} is not installed ({exc})"
    return None


def parse(source: str, grammar: str) -> Node:
    if grammar not in GRAMMARS:
        raise ValueError(f"unknown tree-sitter grammar: {grammar}")
    module, function = GRAMMARS[grammar]
    language = getattr(importlib.import_module(module), function)()
    tree_sitter = importlib.import_module("tree_sitter")
    parser = tree_sitter.Parser(tree_sitter.Language(language))
    return Node(parser.parse(source.encode()).root_node)
