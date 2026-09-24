import ast
from pathlib import Path


def _module_qualified_name(path: str) -> str:
    module_path = Path(path).with_suffix("")
    return ".".join(module_path.parts)


def _visibility(name: str) -> str:
    return "private" if name.startswith("_") else "public"


def _base_repr(node: ast.expr):
    if isinstance(node, (ast.Name, ast.Attribute)):
        return ast.unparse(node)
    return {"dynamic": True, "expression": ast.unparse(node)}


def parse_python_source(path: str, source: str) -> list[dict]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [{"kind": "parse_error", "path": path, "error": str(exc)}]
    return _symbols_from_tree(path, tree)


def _symbols_from_tree(path: str, tree: ast.AST) -> list[dict]:
    module_name = _module_qualified_name(path)
    symbols = [
        {
            "name": module_name,
            "qualified_name": module_name,
            "kind": "module",
            "start_line": 1,
            "end_line": getattr(tree, "end_lineno", None),
            "visibility": "public",
        }
    ]

    def visit_body(body, qualified_prefix, in_class):
        for node in body:
            if isinstance(node, ast.ClassDef):
                qualified_name = f"{qualified_prefix}.{node.name}"
                symbols.append(
                    {
                        "name": node.name,
                        "qualified_name": qualified_name,
                        "kind": "class",
                        "start_line": node.lineno,
                        "end_line": node.end_lineno,
                        "visibility": _visibility(node.name),
                        "bases": [_base_repr(base) for base in node.bases],
                    }
                )
                visit_body(node.body, qualified_name, in_class=True)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified_name = f"{qualified_prefix}.{node.name}"
                symbols.append(
                    {
                        "name": node.name,
                        "qualified_name": qualified_name,
                        "kind": "method" if in_class else "function",
                        "start_line": node.lineno,
                        "end_line": node.end_lineno,
                        "visibility": _visibility(node.name),
                    }
                )
                visit_body(node.body, qualified_name, in_class=False)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                at_module_level = qualified_prefix == module_name
                if not (in_class or at_module_level):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    # Only UPPER_CASE module names count as constants; other
                    # module-level assignments are mostly runtime objects.
                    if not in_class and not target.id.lstrip("_").isupper():
                        continue
                    symbols.append(
                        {
                            "name": target.id,
                            "qualified_name": f"{qualified_prefix}.{target.id}",
                            "kind": "field" if in_class else "constant",
                            "start_line": node.lineno,
                            "end_line": node.end_lineno,
                            "visibility": _visibility(target.id),
                        }
                    )

    visit_body(tree.body, module_name, in_class=False)
    return symbols


def extract_imports(path: str, source: str) -> list[dict]:
    return _imports_from_tree(ast.parse(source, filename=path))


def _imports_from_tree(tree: ast.AST) -> list[dict]:
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                record = {
                    "module": alias.name,
                    "names": [],
                    "level": 0,
                    "line": node.lineno,
                }
                if alias.asname:
                    record["aliases"] = {alias.asname: alias.name}
                imports.append(record)
        elif isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names]
            record = {
                "module": node.module,
                "names": [] if names == ["*"] else names,
                "level": node.level,
                "line": node.lineno,
            }
            if names == ["*"]:
                record["dynamic"] = True
            aliases = {alias.asname: alias.name for alias in node.names if alias.asname}
            if aliases:
                record["aliases"] = aliases
            imports.append(record)

    return imports


class _ScopeTrackingVisitor(ast.NodeVisitor):
    """Tracks the enclosing class and function qualified names while walking."""

    def __init__(self, module_name: str):
        self.callers: list[str] = []
        self.scopes = [module_name]
        self.class_scopes: list[str] = []

    def visit_ClassDef(self, node):
        qualified_name = f"{self.scopes[-1]}.{node.name}"
        self.scopes.append(qualified_name)
        self.class_scopes.append(qualified_name)
        self.generic_visit(node)
        self.class_scopes.pop()
        self.scopes.pop()

    def visit_FunctionDef(self, node):
        prefix = self.callers[-1] if self.callers else self.scopes[-1]
        self.callers.append(f"{prefix}.{node.name}")
        self.generic_visit(node)
        self.callers.pop()

    visit_AsyncFunctionDef = visit_FunctionDef


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else None
    return None


class _ReferenceCollector(_ScopeTrackingVisitor):
    """Collects every usage kind the indexer needs in a single tree walk."""

    def __init__(self, module_name: str):
        super().__init__(module_name)
        self.calls: list[dict] = []
        self.attribute_calls: list[dict] = []
        self.self_references: list[dict] = []
        self.self_calls: list[dict] = []
        self.foreign_accesses: list[dict] = []
        self.name_loads: list[dict] = []
        # `self.x` nodes that are called; they become self_calls, not references.
        self._called_self_attributes: set[int] = set()

    def visit_Call(self, node):
        if self.callers:
            caller = self.callers[-1]
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "self"
                and self.class_scopes
            ):
                self._called_self_attributes.add(id(func))
                self.self_calls.append(
                    {
                        "caller": caller,
                        "class": self.class_scopes[-1],
                        "method": func.attr,
                        "line": node.lineno,
                    }
                )
            if isinstance(func, ast.Name):
                self.calls.append(
                    {"caller": caller, "callee": func.id, "line": node.lineno}
                )
            elif isinstance(func, ast.Attribute):
                obj = _dotted_name(func.value)
                if obj is not None:
                    self.attribute_calls.append(
                        {
                            "caller": caller,
                            "object": obj,
                            "attribute": func.attr,
                            "line": node.lineno,
                        }
                    )
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if self.callers:
            is_self = isinstance(node.value, ast.Name) and node.value.id == "self"
            is_call = id(node) in self._called_self_attributes
            if is_self and self.class_scopes and not is_call:
                self.self_references.append(
                    {
                        "referrer": self.callers[-1],
                        "class": self.class_scopes[-1],
                        "attribute": node.attr,
                        "line": node.lineno,
                    }
                )
            if not is_self:
                self.foreign_accesses.append(
                    {
                        "referrer": self.callers[-1],
                        "attribute": node.attr,
                        "line": node.lineno,
                    }
                )
        self.generic_visit(node)

    def visit_Name(self, node):
        if self.callers and isinstance(node.ctx, ast.Load):
            self.name_loads.append(
                {"referrer": self.callers[-1], "name": node.id, "line": node.lineno}
            )


def _collect(path: str, tree: ast.AST | None) -> _ReferenceCollector:
    collector = _ReferenceCollector(_module_qualified_name(path))
    if tree is not None:
        collector.visit(tree)
    return collector


def _parse_or_none(path: str, source: str) -> ast.AST | None:
    try:
        return ast.parse(source, filename=path)
    except SyntaxError:
        return None


def analyze_python_source(path: str, source: str) -> dict:
    """Run every python extraction on one parse of `source`."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return {
            "symbols": [{"kind": "parse_error", "path": path, "error": str(exc)}],
            "imports": [],
            "calls": [],
            "attribute_calls": [],
            "self_references": [],
            "self_calls": [],
            "foreign_accesses": [],
            "name_loads": [],
        }
    collector = _collect(path, tree)
    return {
        "symbols": _symbols_from_tree(path, tree),
        "imports": _imports_from_tree(tree),
        "calls": collector.calls,
        "attribute_calls": collector.attribute_calls,
        "self_references": collector.self_references,
        "self_calls": collector.self_calls,
        "foreign_accesses": collector.foreign_accesses,
        "name_loads": collector.name_loads,
    }


def extract_static_calls(path: str, source: str) -> list[dict]:
    return _collect(path, _parse_or_none(path, source)).calls


def extract_attribute_calls(path: str, source: str) -> list[dict]:
    return _collect(path, _parse_or_none(path, source)).attribute_calls


def extract_self_attribute_references(path: str, source: str) -> list[dict]:
    return _collect(path, _parse_or_none(path, source)).self_references


def extract_self_method_calls(path: str, source: str) -> list[dict]:
    return _collect(path, _parse_or_none(path, source)).self_calls


def extract_foreign_attribute_accesses(path: str, source: str) -> list[dict]:
    return _collect(path, _parse_or_none(path, source)).foreign_accesses


def extract_name_loads(path: str, source: str) -> list[dict]:
    return _collect(path, _parse_or_none(path, source)).name_loads
