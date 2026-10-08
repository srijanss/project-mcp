"""JavaScript/TypeScript symbols read from a tree-sitter syntax tree."""

from project_mcp.plugins import treesitter
from project_mcp.plugins.javascript.parser import _PASCAL_CASE_RE, _module_qualified_name

_CLASS_TYPES = {"class_declaration", "abstract_class_declaration"}
_FUNCTION_TYPES = {"arrow_function", "function_expression"}
_JSX_TYPES = {"jsx_element", "jsx_self_closing_element"}
# TypeScript declaration node type -> symbol kind
_TYPE_KINDS = {
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "type_alias_declaration": "type_alias",
}


def parse_js_tree(path: str, source: str, grammar: str) -> list[dict]:
    """The symbols declared in `source`, parsed with the `grammar` tree-sitter grammar.

    Beyond what `parse_js_source` finds, each symbol has its end line, nested
    functions are qualified by their parent, and TypeScript interfaces, enums
    and type aliases are found.
    """
    module_name = _module_qualified_name(path)
    symbols = [_symbol(module_name, module_name, "module", 1, len(source.splitlines()) or 1)]
    for statement in treesitter.parse(source, grammar).children:
        declaration = statement.field("declaration") if statement.type == "export_statement" else statement
        if declaration is not None:
            symbols.extend(_declared_symbols(module_name, declaration))
    return symbols


def _declared_symbols(parent: str, node) -> list[dict]:
    """Symbols `node` declares under `parent`, with the functions nested in them."""
    if node.type == "function_declaration":
        return _function_symbols(parent, node.field("name").text, node)
    if node.type in _CLASS_TYPES:
        qualified_name = f"{parent}.{node.field('name').text}"
        symbols = [_symbol(node.field("name").text, qualified_name, "class", *_span(node))]
        for member in node.field("body").children:
            if member.type == "method_definition":
                name = member.field("name").text
                method_name = f"{qualified_name}.{name}"
                symbols.append(_symbol(name, method_name, "method", *_span(member)))
                symbols.extend(_nested_symbols(method_name, member.field("body")))
        return symbols
    if node.type in _TYPE_KINDS:
        name = node.field("name").text
        return [_symbol(name, f"{parent}.{name}", _TYPE_KINDS[node.type], *_span(node))]
    if node.type in ("lexical_declaration", "variable_declaration"):
        return [
            symbol
            for declarator in node.children
            if declarator.type == "variable_declarator"
            and declarator.field("value") is not None
            and declarator.field("value").type in _FUNCTION_TYPES
            and declarator.field("name").type == "identifier"
            for symbol in _function_symbols(parent, declarator.field("name").text, declarator)
        ]
    return []


def _function_symbols(parent: str, name: str, node) -> list[dict]:
    function = node.field("value") or node
    kind = "component" if _PASCAL_CASE_RE.match(name) and _returns_jsx(function) else "function"
    qualified_name = f"{parent}.{name}"
    return [
        _symbol(name, qualified_name, kind, *_span(node)),
        *_nested_symbols(qualified_name, function.field("body")),
    ]


def _nested_symbols(parent: str, node) -> list[dict]:
    """Symbols declared anywhere in a function body, short of anonymous functions."""
    if node is None:
        return []
    symbols = []
    for child in node.children:
        declared = _declared_symbols(parent, child)
        if declared:
            symbols.extend(declared)
        elif child.type not in _FUNCTION_TYPES:
            symbols.extend(_nested_symbols(parent, child))
    return symbols


def _returns_jsx(function) -> bool:
    body = function.field("body")
    if body is None:
        return False
    if body.type != "statement_block":
        return _is_jsx(body)
    return any(_is_jsx(statement.children[0]) for statement in _returns(body) if statement.children)


def _returns(node):
    for child in node.children:
        if child.type == "return_statement":
            yield child
        elif child.type not in _FUNCTION_TYPES | {"function_declaration"}:
            yield from _returns(child)


def _is_jsx(node) -> bool:
    while node.type == "parenthesized_expression" and node.children:
        node = node.children[0]
    return node.type in _JSX_TYPES


def _span(node) -> tuple[int, int]:
    return node.start_line, node.end_line


def _symbol(name: str, qualified_name: str, kind: str, start_line: int, end_line: int) -> dict:
    return {
        "name": name,
        "qualified_name": qualified_name,
        "kind": kind,
        "start_line": start_line,
        "end_line": end_line,
        "visibility": "public",
    }
