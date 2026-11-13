"""Rust symbols read from a tree-sitter syntax tree."""

from pathlib import Path

from project_mcp.plugins import treesitter
from project_mcp.plugins.rust.parser import _module_qualified_name

# tree-sitter node type -> symbol kind
_KINDS = {
    "struct_item": "struct",
    "enum_item": "enum",
    "trait_item": "trait",
    "function_item": "function",
    "function_signature_item": "function",
    "mod_item": "module",
}


def parse_rust_tree(path: str, source: str) -> list[dict]:
    """The symbols declared in `source`, parsed with the rust tree-sitter grammar.

    Unlike `parse_rust_source`, items in inline mods are qualified by the
    mod, and macro_rules bodies stay opaque.
    """
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
    for scope, node in _walk(treesitter.parse(source, "rust"), module_name):
        name = node.field("name").text
        public = any(child.type == "visibility_modifier" for child in node.children)
        symbols.append(
            {
                "name": name,
                "qualified_name": f"{scope}.{name}",
                "kind": _KINDS[node.type],
                "start_line": node.start_line,
                "end_line": None,
                "visibility": "public" if public else "private",
            }
        )
    return symbols


def parse_rust_implements(path: str, source: str, symbols: list[dict]) -> list[tuple[str, str, str]]:
    """`implements` edges from each `impl Trait for Type` whose both ends are in `symbols`.

    Generic parameters and where-clauses are looked through. A `self::`,
    `super::` or (in the crate root) `crate::` path names exactly one item;
    any other path resolves to the innermost known item around the impl.
    """
    known = {symbol["qualified_name"] for symbol in symbols}
    module_name = _module_qualified_name(path)
    crate_root = module_name if Path(path).stem in ("lib", "main") else None
    edges = []
    for scope, impl in _walk(treesitter.parse(source, "rust"), module_name, {"impl_item"}):
        if impl.field("trait") is None:
            continue
        type_name = _resolve(_type_path(impl.field("type")), scope, module_name, crate_root, known)
        trait_name = _resolve(_type_path(impl.field("trait")), scope, module_name, crate_root, known)
        if type_name and trait_name:
            edges.append((type_name, trait_name, "implements"))
    return edges


def _type_path(node) -> list[str]:
    """The path segments a type node refers to, without generics; a path
    from the extern prelude (`::x::T`) starts with an empty segment."""
    if node.type == "generic_type":
        return _type_path(node.field("type"))
    if node.type == "scoped_type_identifier":
        path = node.field("path")
        return (path.text.split("::") if path is not None else [""]) + [node.field("name").text]
    return [node.text]


def _resolve(
    path: list[str], scope: str, module_name: str, crate_root: str | None, known: set[str]
) -> str | None:
    if path[0] == "":
        return None
    if path[0] == "crate":
        if crate_root is None:
            # The crate root is another file; only the item's own name can match here.
            return _resolve(path[-1:], scope, module_name, crate_root, known)
        return _exact(crate_root, path[1:], known)
    if path[0] == "self":
        return _exact(scope, path[1:], known)
    if path[0] == "super":
        while path[0] == "super":
            if scope == module_name:
                return None
            scope, path = scope.rpartition(".")[0], path[1:]
        return _exact(scope, path, known)
    name = ".".join(path)
    while f"{scope}.{name}" not in known:
        if scope == module_name:
            return None
        scope = scope.rpartition(".")[0]
    return f"{scope}.{name}"


def _exact(scope: str, path: list[str], known: set[str]) -> str | None:
    qualified_name = ".".join([scope, *path])
    return qualified_name if qualified_name in known else None


def _walk(node, scope: str, types=_KINDS.keys()):
    """(enclosing module, item) for every item of `types` under `node`.

    An inline `mod` is an item nesting its own scope; a `mod name;`
    declaration is not, since its file is indexed as a module of its own.
    """
    for child in node.children:
        if child.type in types and (child.type != "mod_item" or child.field("body") is not None):
            yield scope, child
        if child.type == "mod_item":
            yield from _walk(child, f"{scope}.{child.field('name').text}", types)
        else:
            yield from _walk(child, scope, types)


def discover_rust_tests(path: str, source: str) -> list[tuple[str, int]]:
    """(qualified name, start line) of the `#[test]` and `#[tokio::test]` functions in `source`.

    Test functions are found wherever they are declared, whether in a
    `#[cfg(test)]` inline mod or at the top of an integration test file.
    """
    return list(_test_functions(treesitter.parse(source, "rust"), _module_qualified_name(path)))


_TEST_ATTRIBUTES = {"test", "tokio::test"}
_COMMENTS = {"line_comment", "block_comment"}


def _test_functions(node, scope: str):
    attributes: list[str] = []
    for child in node.children:
        if child.type == "attribute_item":
            attributes.append(_attribute_path(child))
            continue
        if child.type in _COMMENTS:
            continue
        if child.type == "function_item" and _TEST_ATTRIBUTES.intersection(attributes):
            yield f"{scope}.{child.field('name').text}", child.start_line
        attributes = []
        if child.type == "mod_item":
            if child.field("body") is not None:
                yield from _test_functions(child.field("body"), f"{scope}.{child.field('name').text}")
        elif child.type != "function_item":
            yield from _test_functions(child, scope)


def _attribute_path(attribute_item) -> str:
    attribute = next((child for child in attribute_item.children if child.type == "attribute"), None)
    if attribute is None or not attribute.children:
        return ""
    return attribute.children[0].text
