from pathlib import Path

from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.python.dependencies import (
    declared_dependencies,
    list_python_dependencies,
    normalize_dependency_name,
    python_dependency,
    resolved_versions,
)
from project_mcp.plugins.python.parser import (
    _module_qualified_name,
    analyze_python_source,
)


def resolve_relative_imports(path: str, imports: list[dict]) -> list[dict]:
    """Rewrite `from .x import y` imports of the file at `path` as absolute ones.

    Imports that climb above the project root are left relative, so the
    resolvers that only accept level-0 imports skip them.
    """
    package = list(Path(path).parent.parts)
    resolved = []
    for imp in imports:
        level = imp["level"]
        if level == 0 or level > len(package):
            resolved.append(imp)
            continue
        base = package[: len(package) - level + 1]
        if imp["module"]:
            base = base + [imp["module"]]
        resolved.append({**imp, "module": ".".join(base), "level": 0})
    return resolved


def _with_metadata(symbol: dict) -> dict:
    if symbol["kind"] != "class":
        return symbol
    return {**symbol, "metadata": {"bases": symbol["bases"]}}


def _same_file_member_resolver(symbols: list[dict], kind: str):
    """A `(class, name) -> qualified name` lookup for members of one kind.

    A member the class doesn't define is looked up on its base classes in the
    same file, depth-first and left to right.
    """
    module_name = next(
        (s["qualified_name"] for s in symbols if s.get("kind") == "module"), None
    )
    members = {s["qualified_name"] for s in symbols if s.get("kind") == kind}
    class_bases = {
        s["qualified_name"]: [
            f"{module_name}.{base}"
            for base in s["bases"]
            if isinstance(base, str) and "." not in base
        ]
        for s in symbols
        if s.get("kind") == "class"
    }

    def find(class_name: str, name: str, visited: set[str]) -> str | None:
        if class_name in visited or class_name not in class_bases:
            return None
        visited.add(class_name)
        if f"{class_name}.{name}" in members:
            return f"{class_name}.{name}"
        for base in class_bases[class_name]:
            found = find(base, name, visited)
            if found is not None:
                return found
        return None

    return lambda class_name, name: find(class_name, name, set())


def _same_file_edges(symbols: list[dict], parsed: dict) -> list[tuple[str, str, str]]:
    """Inheritance, call and reference edges whose both ends are in this file.

    Each kind of evidence links a (source, target) pair once.
    """
    module_name = next(s["qualified_name"] for s in symbols if s["kind"] == "module")
    known = {s["qualified_name"] for s in symbols}
    resolve_method = _same_file_member_resolver(symbols, "method")
    resolve_field = _same_file_member_resolver(symbols, "field")

    evidence = [
        (
            "inherits",
            [
                (s["qualified_name"], f"{module_name}.{base}")
                for s in symbols
                if s["kind"] == "class"
                for base in s["bases"]
                if isinstance(base, str) and "." not in base
            ],
        ),
        (
            "calls",
            [(c["caller"], f"{module_name}.{c['callee']}") for c in parsed["calls"]],
        ),
        (
            "calls",
            [
                (c["caller"], resolve_method(c["class"], c["method"]))
                for c in parsed["self_calls"]
            ],
        ),
        (
            "references",
            [
                (r["referrer"], f"{r['class']}.{r['attribute']}")
                for r in parsed["self_references"]
            ],
        ),
        (
            "references",
            [
                (
                    a["referrer"],
                    resolve_field(f"{module_name}.{a['object']}", a["attribute"]),
                )
                for a in parsed["foreign_accesses"]
                if a["object"]
            ],
        ),
    ]

    edges = []
    for relationship_type, pairs in evidence:
        seen = set()
        for source, target in pairs:
            if source in known and target in known and (source, target) not in seen:
                seen.add((source, target))
                edges.append((source, target, relationship_type))
    return edges


class PythonAnalyzer:
    def module_name(self, path: str) -> str:
        """The qualified name of the module symbol this file is indexed as."""
        return _module_qualified_name(path)

    def list_dependencies(self, project_root: Path) -> list[dict]:
        """The dependencies this project's manifests declare for the ecosystem."""
        return list_python_dependencies(Path(project_root))

    def dependency_key(self, name: str) -> str:
        """The name two spellings of one package share (PEP 503 normalized)."""
        return normalize_dependency_name(name)

    def undeclared_dependency(self, project_root: Path, name: str) -> dict | None:
        """`name` at its uv.lock version when the project declares no dependencies."""
        root = Path(project_root)
        if declared_dependencies(root):
            return None
        version = resolved_versions(root).get(normalize_dependency_name(name))
        return python_dependency(name, version, "resolved") if version else None

    def is_test_file(self, path: Path) -> bool:
        path = Path(path)
        in_test_dir = bool({"tests", "test"} & set(path.parts[:-1]))
        return in_test_dir or path.stem.startswith("test_") or path.stem.endswith("_test")

    def analyze(self, path: str, source: str) -> FileAnalysis:
        parsed = analyze_python_source(path, source)
        parsed["imports"] = resolve_relative_imports(path, parsed["imports"])
        symbols = parsed["symbols"]
        if len(symbols) == 1 and symbols[0].get("kind") == "parse_error":
            return FileAnalysis(extra=parsed)
        return FileAnalysis(
            symbols=[_with_metadata(symbol) for symbol in symbols],
            symbol_edges=_same_file_edges(symbols, parsed),
            imports=[
                (imp["module"], tuple(imp.get("names", [])))
                for imp in parsed["imports"]
                if not imp.get("dynamic") and imp["level"] == 0 and imp["module"]
            ],
            extra=parsed,
        )

    def link_cross_file(self, context) -> None:
        from project_mcp.plugins.python import linking

        linking.link_cross_file(context)

    def link_test_evidence(self, context) -> None:
        from project_mcp.plugins.python import linking

        linking.link_test_evidence(context)

    def resolve_import(self, importer: str, spec: tuple[str, tuple[str, ...]]) -> list[str]:
        """`import a.b` -> a/b.py; `from a import x, y` also tries a/x.py, a/y.py."""
        module, names = spec
        module_path = module.replace(".", "/")
        return [f"{module_path}.py"] + [f"{module_path}/{name}.py" for name in names]
