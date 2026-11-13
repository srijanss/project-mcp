"""Which items each Rust function calls or names through a `use` path."""

import re
import tomllib
from pathlib import Path

from project_mcp.plugins import treesitter
from project_mcp.plugins.rust.parser import _module_qualified_name

# A call inside a macro's token tree, which tree-sitter leaves unparsed:
# a path followed by `(`, not a method (`.f(`), a macro (`f!(`) or a path tail.
_CALL_IN_TOKENS = re.compile(r"(?<![\w.:!])((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\s*\(")
_KEYWORDS = {
    "as", "async", "await", "else", "fn", "for", "if", "in", "let", "loop",
    "match", "move", "mut", "ref", "return", "unsafe", "where", "while",
}
# Tokens inside a macro that hold text rather than code.
_NOT_CODE = {
    "string_literal", "raw_string_literal", "char_literal", "line_comment", "block_comment",
}
_USE = re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?use\s+(.*?);?$", re.DOTALL)
_TURBOFISH = re.compile(r"::<[^>]*>")
# Directories a crate's files live in; the crate's own path is what precedes them.
_CRATE_DIRS = ("src", "tests", "benches", "examples")


def rust_file_links(
    path: str, source: str, crates: dict[str, str], known, index: dict[str, str] | None = None
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """`rust_symbol_uses` and `rust_use_imports` for one file, parsing it once."""
    index = symbol_index(known) if index is None else index
    tree = treesitter.parse(source, "rust")
    return (
        rust_symbol_uses(path, source, crates, known, index=index, tree=tree),
        rust_use_imports(path, source, crates, known, index=index, tree=tree),
    )


def rust_symbol_uses(
    path: str, source: str, crates: dict[str, str], known, index: dict[str, str] | None = None, tree=None
) -> list[tuple[str, str, str]]:
    """(function, item, "calls" | "references") for each item in `known` a function uses.

    `crates` maps each workspace crate's name to its directory as a dotted
    module prefix ("" for a crate at the project root). A call resolves
    through the function's module, its `use` bindings and glob imports; a
    name bound by `use` that is not called is a reference. Linking many
    files, pass the `symbol_index(known)` built once for them all.
    """
    resolver = _Resolver(_crate_dir(path), crates, symbol_index(known) if index is None else index)
    edges: list[tuple[str, str, str]] = []
    tree = treesitter.parse(source, "rust") if tree is None else tree
    _visit_module(tree, _module_qualified_name(path), resolver, edges)
    called = {(caller, target) for caller, target, kind in edges if kind == "calls"}
    # A called name is also an identifier; the call is the stronger evidence.
    return [
        edge for edge in dict.fromkeys(edges)
        if edge[2] == "calls" or (edge[0], edge[1]) not in called
    ]


def rust_use_imports(
    path: str, source: str, crates: dict[str, str], known, index: dict[str, str] | None = None, tree=None
) -> list[str]:
    """Each item in `known` that one of the file's `use` declarations names.

    Declarations in inline mods and in function bodies count too; glob
    imports name no single item and are left out.
    """
    resolver = _Resolver(_crate_dir(path), crates, symbol_index(known) if index is None else index)
    imports: list[str] = []
    tree = treesitter.parse(source, "rust") if tree is None else tree
    _visit_imports(tree, _module_qualified_name(path), resolver, imports)
    return list(dict.fromkeys(imports))


def _visit_imports(node, scope: str, resolver: "_Resolver", imports: list, outer: dict | None = None) -> None:
    local, _ = _use_bindings(node)
    bindings = _scope_bindings(outer or {}, local)
    targets = [resolver.resolve([name], scope, bindings, []) for name in local]
    # `use path::Trait as _;` binds no name but still brings the trait in.
    targets += [resolver.resolve(path, scope, bindings, []) for path, name in _use_paths(node) if name == "_"]
    imports.extend(target for target in targets if target is not None)
    for child in node.children:
        if child.type == "mod_item":
            body = child.field("body")
            if body is not None:
                # An inline mod starts a new scope: it inherits no imports.
                _visit_imports(body, f"{scope}.{child.field('name').text}", resolver, imports)
        elif child.type != "token_tree":
            _visit_imports(child, scope, resolver, imports, bindings)


def workspace_crates(project_root: Path, paths) -> dict[str, str]:
    """Crate name (as `use` paths spell it) → dotted crate dir, from each file's Cargo.toml."""
    crates: dict[str, str] = {}
    for crate_dir in dict.fromkeys(_crate_dir(path) for path in paths):
        manifest = Path(project_root, *crate_dir.split(".") if crate_dir else ()) / "Cargo.toml"
        try:
            name = tomllib.loads(manifest.read_text(encoding="utf-8"))["package"]["name"]
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError):
            continue
        if isinstance(name, str):
            crates[name.replace("-", "_")] = crate_dir
    return crates


def symbol_index(known) -> dict[str, str]:
    """Each known qualified name, and the path Rust spells it by, → the qualified name.

    A `foo/mod.rs` file is indexed as `foo.mod` but named `foo` in paths.
    """
    index = {name: name for name in known}
    for name in known:
        index.setdefault(_module_path(name), name)
    return index


def _crate_dir(path: str) -> str:
    parts = path.split("/")[:-1]
    for index, part in enumerate(parts):
        if part in _CRATE_DIRS:
            return ".".join(parts[:index])
    return ".".join(parts)


class _Resolver:
    def __init__(self, crate_dir: str, crates: dict[str, str], by_path: dict[str, str]) -> None:
        self.crate_dir = crate_dir
        self.crates = crates
        self.by_path = by_path

    def roots(self, crate_dir: str) -> list[str]:
        prefix = f"{crate_dir}." if crate_dir else ""
        return [f"{prefix}src.lib", f"{prefix}src.main", f"{prefix}src"]

    def candidates(self, segments: list[str], scope: str) -> list[str]:
        scope = _module_path(scope)
        head, rest = segments[0], segments[1:]
        if head == "crate":
            bases = self.roots(self.crate_dir)
        elif head == "super":
            parent = scope.rsplit(".", 1)[0]
            bases = [parent]
            if parent in self.roots(self.crate_dir):
                bases = self.roots(self.crate_dir)
        elif head == "self":
            bases = [scope]
        elif head in self.crates:
            bases = self.roots(self.crates[head])
        else:
            bases, rest = [scope], segments
        return [".".join([base, *rest]) for base in bases]

    def resolve(self, segments: list[str], scope: str, bindings: dict, globs: list) -> str | None:
        if segments[0] in bindings:
            # Bindings are already expanded (see `_scope_bindings`), so one step does.
            segments = bindings[segments[0]] + segments[1:]
            return self._first(self.candidates(segments, scope))
        found = self._first(self.candidates(segments, scope))
        if found is None and len(segments) == 1:
            for glob in globs:
                found = self._first(self.candidates(glob + segments, scope))
                if found is not None:
                    break
        return found

    def _first(self, candidates: list[str]) -> str | None:
        return next((self.by_path[name] for name in candidates if name in self.by_path), None)


def _module_path(name: str) -> str:
    """The name as Rust paths spell it: `mod` is a keyword, so only a mod.rs file adds it.

    The crate's own directory precedes its `src` (or `tests`, ...) and may
    well be called `mod`; only the segments after it are module names.
    """
    parts = name.split(".")
    start = next((index + 1 for index, part in enumerate(parts) if part in _CRATE_DIRS), 0)
    return ".".join(parts[:start] + [part for part in parts[start:] if part != "mod"])


def _visit_module(node, scope: str, resolver: _Resolver, edges: list) -> None:
    local, globs = _use_bindings(node)
    bindings = _scope_bindings({}, local)
    _visit_items(node, scope, bindings, globs, resolver, edges)


def _visit_items(node, scope, bindings, globs, resolver, edges) -> None:
    for child in node.children:
        if child.type == "mod_item":
            body = child.field("body")
            if body is not None:
                _visit_module(body, f"{scope}.{child.field('name').text}", resolver, edges)
        elif child.type == "function_item":
            caller = f"{scope}.{child.field('name').text}"
            _visit_body(child.field("body"), caller, scope, bindings, globs, resolver, edges)
        elif child.type != "token_tree":
            # A macro's tokens hold no parsed items and can nest very deep.
            _visit_items(child, scope, bindings, globs, resolver, edges)


def _visit_body(node, caller, scope, bindings, globs, resolver, edges) -> None:
    if node is None:
        return
    if node.type == "block":
        # A block's `use` declarations bind names for that block alone.
        local_bindings, local_globs = _use_bindings(node)
        bindings, globs = _scope_bindings(bindings, local_bindings), [*globs, *local_globs]
    for child in node.children:
        if child.type == "use_declaration":
            continue
        if child.type == "call_expression":
            function = child.field("function")
            if function is not None and function.type == "generic_function":
                function = function.field("function")
            if function is not None and function.type in ("identifier", "scoped_identifier"):
                _add(edges, caller, resolver.resolve(_segments(function.text), scope, bindings, globs), "calls")
        elif child.type == "token_tree":
            # A macro's tokens are scanned once, nested token trees included.
            for match in _CALL_IN_TOKENS.finditer(_code_text(child)):
                segments = _segments(match.group(1))
                if segments[0] not in _KEYWORDS:
                    _add(edges, caller, resolver.resolve(segments, scope, bindings, globs), "calls")
            for token in _tokens(child):
                if token.type == "identifier" and token.text in bindings:
                    _add(edges, caller, resolver.resolve([token.text], scope, bindings, globs), "references")
            continue
        elif child.type in ("identifier", "type_identifier") and child.text in bindings:
            _add(edges, caller, resolver.resolve([child.text], scope, bindings, globs), "references")
        _visit_body(child, caller, scope, bindings, globs, resolver, edges)


def _code_text(token_tree) -> str:
    """The token tree's text with its strings and comments blanked out."""
    text, parts, cursor = token_tree.text, [], 0
    for literal in (token for token in _tokens(token_tree) if token.type in _NOT_CODE):
        # Literals come in source order, so each is found after the last.
        index = text.find(literal.text, cursor)
        if index < 0:
            continue
        parts += [text[cursor:index], " "]
        cursor = index + len(literal.text)
    parts.append(text[cursor:])
    return "".join(parts)


def _tokens(token_tree):
    """The tokens inside a token tree and its nested ones, in source order.

    Walked with a stack: macro arguments can nest deeper than Python recursion.
    """
    stack = list(reversed(token_tree.children))
    while stack:
        token = stack.pop()
        if token.type == "token_tree":
            stack.extend(reversed(token.children))
        else:
            yield token


def _add(edges: list, caller: str, target: str | None, kind: str) -> None:
    if target is not None:
        edges.append((caller, target, kind))


def _segments(path_text: str) -> list[str]:
    return [segment for segment in _TURBOFISH.sub("", path_text).split("::") if segment]


def _use_bindings(node) -> tuple[dict[str, list[str]], list[list[str]]]:
    """The names a module's (or block's) `use` declarations bind, and its glob imports."""
    bindings: dict[str, list[str]] = {}
    globs: list[list[str]] = []
    for segments, name in _use_paths(node):
        if name == "*":
            globs.append(segments)
        elif name != "_":
            bindings[name] = segments
    return bindings, globs


def _scope_bindings(outer: dict, local: dict) -> dict:
    """The names bound in a scope, each expanded to the path it named where it was declared.

    A declaration may build on another alias (`use a::T as S;`); expanding it
    here keeps it pointing there when an inner block rebinds `a`. Each name
    is expanded at most once, so `use foo::foo;` or a cycle cannot loop.
    Most nodes declare nothing; they share (and must not change) `outer`.
    """
    if not local:
        return outer
    expanded = dict(outer)
    for name, segments in local.items():
        seen = {name}
        while segments[0] in local and segments[0] not in seen:
            seen.add(segments[0])
            segments = local[segments[0]] + segments[1:]
        if segments[0] in outer and segments[0] not in local:
            # An inherited binding was expanded where it was declared; this
            # scope's names must not re-expand it.
            segments = outer[segments[0]] + segments[1:]
        expanded[name] = segments
    return expanded


def _use_paths(node):
    """(path segments, bound name) for each path the node's own `use` declarations name."""
    if node is None:
        return
    for declaration in (child for child in node.children if child.type == "use_declaration"):
        match = _USE.match(declaration.text.strip())
        if match is None:
            continue
        for segments, name in _expand_use(match.group(1), []):
            if segments:
                yield segments, name


def _expand_use(text: str, prefix: list[str]):
    """(path segments, bound name) for each path a `use` tree names; "*" marks a glob."""
    text = re.sub(r"\s*(::|,|\{|\})\s*", r"\1", text.strip())
    if text.endswith("}"):
        brace = text.index("{")
        base = prefix + [segment for segment in text[:brace].split("::") if segment]
        for part in _split_top_level(text[brace + 1 : -1]):
            if part:
                yield from _expand_use(part, base)
    elif text.endswith("*"):
        yield prefix + [segment for segment in text[:-1].split("::") if segment], "*"
    else:
        path, _, alias = text.partition(" as ")
        segments = prefix + [segment for segment in path.split("::") if segment]
        if segments and segments[-1] == "self":
            segments = segments[:-1]
        if segments:
            yield segments, alias.strip() or segments[-1]


def _split_top_level(text: str) -> list[str]:
    parts, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return [part.strip() for part in parts]
