"""JavaScript/TypeScript symbols read from a tree-sitter syntax tree."""

from project_mcp.plugins import treesitter
from project_mcp.plugins.javascript.parser import _PASCAL_CASE_RE, _module_qualified_name

_CLASS_TYPES = {"class_declaration", "abstract_class_declaration"}
_FUNCTION_TYPES = {"arrow_function", "function_expression"}
# Every node that opens a function scope of its own
_SCOPE_TYPES = _FUNCTION_TYPES | {
    "function_declaration",
    "method_definition",
    "generator_function",
    "generator_function_declaration",
}
# Pattern node type -> field holding the name(s) it binds
_PATTERN_FIELDS = {
    "assignment_pattern": "left",
    "object_assignment_pattern": "left",
    "pair_pattern": "value",
    "required_parameter": "pattern",
    "optional_parameter": "pattern",
}
_PATTERN_CONTAINERS = {"formal_parameters", "object_pattern", "array_pattern", "rest_pattern"}
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
        elif statement.field("value") is not None:
            function = _wrapped_function(statement.field("value"))
            if function is not None:
                symbols.extend(_function_symbols(module_name, function.field("name").text, function))
    return symbols


def _wrapped_function(node):
    """The named function expression at the core of wrapper calls such as `memo(function X() {})`."""
    while node.type == "call_expression":
        arguments = [a for a in node.field("arguments").children if a.type != "comment"]
        if not arguments:
            return None
        node = arguments[0]
    if node.type == "function_expression" and node.field("name") is not None:
        return node
    return None


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


def parse_js_calls(path: str, source: str, grammar: str, symbols: list[dict]) -> list[tuple[str, str, str]]:
    """`calls` edges between `symbols`, one per (caller, callee) pair, in source order.

    A plain call `f()` resolves to the innermost known `f` around the caller
    and `this.m()` to a method of the enclosing class. Calls through any
    other expression, or through a parameter or variable shadowing `f`,
    are dynamic and left out.
    """
    known = {symbol["qualified_name"] for symbol in symbols}
    module_name = _module_qualified_name(path)
    edges = []
    tree = treesitter.parse(source, grammar)
    for caller, class_name, bound, call in _calls(tree, module_name, None, {}):
        callee = _callee(call.field("function"), caller, class_name, bound, module_name, known)
        edge = (caller, callee, "calls")
        if caller in known and callee is not None and edge not in edges:
            edges.append(edge)
    return edges


def _calls(node, scope: str, class_name: str | None, bound: dict[str, str]):
    """(caller, enclosing class, local bindings, call node) for every call under `node`.

    `bound` maps each name a parameter, variable or catch clause binds
    around the call to the scope it binds it in.
    """
    for child in node.children:
        child_scope, child_class, child_bound = scope, class_name, bound
        name = child.field("name")
        if child.type in ("function_declaration", "method_definition") or (
            child.type == "variable_declarator"
            and child.field("value") is not None
            and child.field("value").type in _FUNCTION_TYPES
        ):
            child_scope = f"{scope}.{name.text}"
        elif child.type in _CLASS_TYPES:
            child_scope = child_class = f"{scope}.{name.text}"
        if child.type in _SCOPE_TYPES:
            child_bound = bound | dict.fromkeys(_local_names(child), child_scope)
        elif child.type == "catch_clause" and child.field("parameter") is not None:
            child_bound = bound | dict.fromkeys(_bound_names(child.field("parameter")), scope)
        if child.type == "call_expression":
            yield scope, class_name, bound, child
        yield from _calls(child, child_scope, child_class, child_bound)


def _local_names(function) -> list[str]:
    """The names `function`'s parameters bind, and its own variables not
    holding a function (those are symbols of their own)."""
    names = []
    for field in ("parameters", "parameter"):
        if function.field(field) is not None:
            names += _bound_names(function.field(field))
    if function.field("body") is not None:
        names += _declared_names(function.field("body"))
    return names


def _declared_names(node) -> list[str]:
    names = []
    for child in node.children:
        if child.type in _SCOPE_TYPES:
            continue
        value = child.field("value")
        if child.type == "variable_declarator" and (value is None or value.type not in _FUNCTION_TYPES):
            names += _bound_names(child.field("name"))
        names += _declared_names(child)
    return names


def _bound_names(pattern) -> list[str]:
    """The names a parameter or destructuring `pattern` binds, leaving out
    default values and type annotations."""
    if pattern.type in ("identifier", "shorthand_property_identifier_pattern"):
        return [pattern.text]
    if pattern.type in _PATTERN_FIELDS:
        inner = pattern.field(_PATTERN_FIELDS[pattern.type])
        return _bound_names(inner) if inner is not None else []
    if pattern.type in _PATTERN_CONTAINERS:
        return [name for child in pattern.children for name in _bound_names(child)]
    return []


def _callee(
    function, caller: str, class_name: str | None, bound: dict[str, str], module_name: str, known: set[str]
) -> str | None:
    if function.type == "identifier":
        scope = caller
        while True:
            if bound.get(function.text) == scope:
                return None
            if f"{scope}.{function.text}" in known:
                return f"{scope}.{function.text}"
            if scope == module_name:
                return None
            scope = scope.rpartition(".")[0]
    if (
        function.type == "member_expression"
        and function.field("object").type == "this"
        and class_name is not None
        and f"{class_name}.{function.field('property').text}" in known
    ):
        return f"{class_name}.{function.field('property').text}"
    return None
