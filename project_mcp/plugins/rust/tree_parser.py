"""Rust symbols read from a tree-sitter syntax tree."""

from project_mcp.plugins import treesitter
from project_mcp.plugins.rust.parser import _module_qualified_name

# tree-sitter node type -> symbol kind
_KINDS = {
    "struct_item": "struct",
    "enum_item": "enum",
    "trait_item": "trait",
    "function_item": "function",
    "function_signature_item": "function",
}


def parse_rust_tree(path: str, source: str) -> list[dict]:
    """The symbols `parse_rust_source` reports, parsed with the rust tree-sitter grammar."""
    module_name = _module_qualified_name(path)
    symbols = [
        {
            "name": module_name,
            "qualified_name": module_name,
            "kind": "module",
            "start_line": 1,
            "end_line": len(source.splitlines()) or 1,
            "visibility": "public",
        }
    ]
    for node in _walk(treesitter.parse(source, "rust")):
        name = node.field("name").text
        public = any(child.type == "visibility_modifier" for child in node.children)
        symbols.append(
            {
                "name": name,
                "qualified_name": f"{module_name}.{name}",
                "kind": _KINDS[node.type],
                "start_line": node.start_line,
                "end_line": None,
                "visibility": "public" if public else "private",
            }
        )
    return symbols


def _walk(node):
    for child in node.children:
        if child.type in _KINDS:
            yield child
        yield from _walk(child)
