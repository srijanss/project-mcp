"""JavaScript/TypeScript symbols read from a tree-sitter syntax tree."""

from project_mcp.plugins import treesitter
from project_mcp.plugins.javascript.parser import _PASCAL_CASE_RE, _module_qualified_name

_CLASS_TYPES = {"class_declaration", "abstract_class_declaration"}
_FUNCTION_TYPES = {"arrow_function", "function_expression"}
_JSX_TYPES = {"jsx_element", "jsx_self_closing_element"}


def parse_js_tree(path: str, source: str, grammar: str) -> list[dict]:
    """The symbols `parse_js_source` reports, parsed with the `grammar` tree-sitter grammar."""
    module_name = _module_qualified_name(path)
    symbols = [_symbol(module_name, module_name, "module", 1, len(source.splitlines()) or 1)]
    for statement in treesitter.parse(source, grammar).children:
        declaration = statement.field("declaration") if statement.type == "export_statement" else statement
        if declaration is not None:
            symbols.extend(_declared_symbols(module_name, declaration))
    return symbols


def _declared_symbols(module_name: str, node) -> list[dict]:
    if node.type == "function_declaration":
        name = node.field("name").text
        return [_function_symbol(module_name, name, node)]
    if node.type in _CLASS_TYPES:
        qualified_name = f"{module_name}.{node.field('name').text}"
        symbols = [_symbol(node.field("name").text, qualified_name, "class", node.start_line)]
        for member in node.field("body").children:
            if member.type == "method_definition":
                name = member.field("name").text
                symbols.append(_symbol(name, f"{qualified_name}.{name}", "method", member.start_line))
        return symbols
    if node.type in ("lexical_declaration", "variable_declaration"):
        return [
            _function_symbol(module_name, declarator.field("name").text, declarator)
            for declarator in node.children
            if declarator.type == "variable_declarator"
            and declarator.field("value") is not None
            and declarator.field("value").type in _FUNCTION_TYPES
            and declarator.field("name").type == "identifier"
        ]
    return []


def _function_symbol(module_name: str, name: str, node) -> dict:
    function = node.field("value") or node
    kind = "component" if _PASCAL_CASE_RE.match(name) and _returns_jsx(function) else "function"
    return _symbol(name, f"{module_name}.{name}", kind, node.start_line)


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


def _symbol(name: str, qualified_name: str, kind: str, start_line: int, end_line=None) -> dict:
    return {
        "name": name,
        "qualified_name": qualified_name,
        "kind": kind,
        "start_line": start_line,
        "end_line": end_line,
        "visibility": "public",
    }
