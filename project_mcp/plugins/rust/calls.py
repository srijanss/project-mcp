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
_USE = re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?use\s+(.*?);?$", re.DOTALL)
_TURBOFISH = re.compile(r"::<[^>]*>")
# Directories a crate's files live in; the crate's own path is what precedes them.
_CRATE_DIRS = ("src", "tests", "benches", "examples")


def rust_symbol_uses(
    path: str, source: str, crates: dict[str, str], known
) -> list[tuple[str, str, str]]:
    """(function, item, "calls" | "references") for each item in `known` a function uses.

    `crates` maps each workspace crate's name to its directory as a dotted
    module prefix ("" for a crate at the project root). A call resolves
    through the function's module, its `use` bindings and glob imports; a
    name bound by `use` that is not called is a reference.
    """
    resolver = _Resolver(_crate_dir(path), crates, known)
    edges: list[tuple[str, str, str]] = []
    _visit_module(treesitter.parse(source, "rust"), _module_qualified_name(path), resolver, edges)
    called = {(caller, target) for caller, target, kind in edges if kind == "calls"}
    # A called name is also an identifier; the call is the stronger evidence.
    return [
        edge for edge in dict.fromkeys(edges)
        if edge[2] == "calls" or (edge[0], edge[1]) not in called
    ]


def workspace_crates(project_root: Path, paths) -> dict[str, str]:
    """Crate name (as `use` paths spell it) → dotted crate dir, from each file's Cargo.toml."""
    crates: dict[str, str] = {}
    for crate_dir in dict.fromkeys(_crate_dir(path) for path in paths):
        manifest = Path(project_root, *crate_dir.split(".") if crate_dir else ()) / "Cargo.toml"
        try:
            name = tomllib.loads(manifest.read_text())["package"]["name"]
        except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError):
            continue
        if isinstance(name, str):
            crates[name.replace("-", "_")] = crate_dir
    return crates


def _crate_dir(path: str) -> str:
    parts = path.split("/")[:-1]
    for index, part in enumerate(parts):
        if part in _CRATE_DIRS:
            return ".".join(parts[:index])
    return ".".join(parts)


class _Resolver:
    def __init__(self, crate_dir: str, crates: dict[str, str], known) -> None:
        self.crate_dir = crate_dir
        self.crates = crates
        # A `foo/mod.rs` file is indexed as `foo.mod` but named `foo` in paths.
        self.by_path = {_module_path(name): name for name in known}
        self.by_path.update({name: name for name in known})

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
    """The name as Rust paths spell it: `mod` is a keyword, so only a mod.rs file adds it."""
    return ".".join(part for part in name.split(".") if part != "mod")


def _visit_module(node, scope: str, resolver: _Resolver, edges: list) -> None:
    bindings, globs = _use_bindings(node)
    _visit_items(node, scope, bindings, globs, resolver, edges)


def _visit_items(node, scope, bindings, globs, resolver, edges) -> None:
    for child in node.children:
        if child.type == "mod_item":
            body = child.field("body")
            if body is not None:
                _visit_module(body, f"{scope}.{child.field('name').text}", resolver, edges)
        elif child.type == "function_item":
            caller = f"{scope}.{child.field('name').text}"
            local_bindings, local_globs = _use_bindings(child.field("body"), nested=True)
            _visit_body(
                child.field("body"),
                caller,
                scope,
                {**bindings, **local_bindings},
                [*globs, *local_globs],
                resolver,
                edges,
            )
        else:
            _visit_items(child, scope, bindings, globs, resolver, edges)


def _visit_body(node, caller, scope, bindings, globs, resolver, edges) -> None:
    if node is None:
        return
    for child in node.children:
        if child.type == "call_expression":
            function = child.field("function")
            if function is not None and function.type == "generic_function":
                function = function.field("function")
            if function is not None and function.type in ("identifier", "scoped_identifier"):
                _add(edges, caller, resolver.resolve(_segments(function.text), scope, bindings, globs), "calls")
        elif child.type == "token_tree":
            for match in _CALL_IN_TOKENS.finditer(child.text):
                segments = _segments(match.group(1))
                if segments[0] not in _KEYWORDS:
                    _add(edges, caller, resolver.resolve(segments, scope, bindings, globs), "calls")
        elif child.type in ("identifier", "type_identifier") and child.text in bindings:
            _add(edges, caller, resolver.resolve([child.text], scope, bindings, globs), "references")
        _visit_body(child, caller, scope, bindings, globs, resolver, edges)


def _add(edges: list, caller: str, target: str | None, kind: str) -> None:
    if target is not None:
        edges.append((caller, target, kind))


def _segments(path_text: str) -> list[str]:
    return [segment for segment in _TURBOFISH.sub("", path_text).split("::") if segment]


def _use_bindings(node, nested: bool = False) -> tuple[dict[str, list[str]], list[list[str]]]:
    """The names a module's (or block's) `use` declarations bind, and its glob imports."""
    bindings: dict[str, list[str]] = {}
    globs: list[list[str]] = []
    if node is None:
        return bindings, globs
    for declaration in _use_declarations(node, nested):
        match = _USE.match(declaration.text.strip())
        if match is None:
            continue
        for segments, name in _expand_use(match.group(1), []):
            if not segments:
                continue
            if name == "*":
                globs.append(segments)
            elif name != "_":
                bindings[name] = segments
    return bindings, globs


def _use_declarations(node, nested: bool):
    for child in node.children:
        if child.type == "use_declaration":
            yield child
        elif nested and child.type not in ("function_item", "mod_item"):
            yield from _use_declarations(child, nested)


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
