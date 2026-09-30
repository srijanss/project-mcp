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
        # Decorators, bases and keywords are evaluated in the enclosing scope.
        for expression in [
            *node.decorator_list,
            *node.bases,
            *(keyword.value for keyword in node.keywords),
        ]:
            self.visit(expression)
        qualified_name = f"{self.scopes[-1]}.{node.name}"
        self.scopes.append(qualified_name)
        self.class_scopes.append(qualified_name)
        for statement in node.body:
            self.visit(statement)
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


def _annotated_class(annotation: ast.expr | None) -> str | None:
    """The class named by `Cls`, `mod.Cls` or `Cls | None`, if that's all it is."""
    if (
        isinstance(annotation, ast.BinOp)
        and isinstance(annotation.op, ast.BitOr)
        and isinstance(annotation.right, ast.Constant)
        and annotation.right.value is None
    ):
        annotation = annotation.left
    if annotation is None:
        return None
    return _dotted_name(annotation)


def _constructed_class(value: ast.expr) -> str | None:
    """The class in `Cls(...)` / `mod.Cls(...)`; CapWords names only."""
    if not isinstance(value, ast.Call):
        return None
    name = _dotted_name(value.func)
    if name is None or not name.rsplit(".", 1)[-1][:1].isupper():
        return None
    return name


class _FunctionTypes:
    """Receiver types of one function's local names, and its method calls."""

    UNTYPED = None

    def __init__(self):
        self.types: dict[str, set] = {}
        self.calls: list[tuple[str, str, str, int]] = []

    def assign(self, name: str, class_name: str | None) -> None:
        self.types.setdefault(name, set()).add(class_name)

    def typed_calls(self) -> list[dict]:
        resolved = []
        for caller, name, method, line in self.calls:
            classes = self.types.get(name, {self.UNTYPED})
            if len(classes) == 1 and self.UNTYPED not in classes:
                (class_name,) = classes
                resolved.append(
                    {"caller": caller, "class": class_name, "method": method, "line": line}
                )
        return resolved


class _ReferenceCollector(_ScopeTrackingVisitor):
    """Collects every usage kind the indexer needs in a single tree walk."""

    def __init__(self, module_name: str):
        super().__init__(module_name)
        self.calls: list[dict] = []
        self.attribute_calls: list[dict] = []
        self.self_references: list[dict] = []
        self.self_calls: list[dict] = []
        self.typed_calls: list[dict] = []
        self.foreign_accesses: list[dict] = []
        self.name_loads: list[dict] = []
        # `self.x` nodes that are called; they become self_calls, not references.
        self._called_self_attributes: set[int] = set()
        self._function_types: list[_FunctionTypes] = []
        # Name targets of `x = Cls()`, already typed by visit_Assign.
        self._typed_targets: set[int] = set()

    def visit_FunctionDef(self, node):
        function_types = _FunctionTypes()
        arguments = node.args
        for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]:
            function_types.assign(arg.arg, _annotated_class(arg.annotation))
        # *args / **kwargs are a tuple and a dict, whatever their annotation.
        for arg in filter(None, [arguments.vararg, arguments.kwarg]):
            function_types.assign(arg.arg, _FunctionTypes.UNTYPED)
        self._function_types.append(function_types)
        super().visit_FunctionDef(node)
        self._function_types.pop()
        self.typed_calls.extend(function_types.typed_calls())

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node):
        if self._function_types and len(node.targets) == 1:
            target = node.targets[0]
            class_name = _constructed_class(node.value)
            if isinstance(target, ast.Name) and class_name is not None:
                self._function_types[-1].assign(target.id, class_name)
                self._typed_targets.add(id(target))
        self.generic_visit(node)

    def visit_Call(self, node):
        if self.callers:
            caller = self.callers[-1]
            func = node.func
            if (
                self._function_types
                and isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id != "self"
            ):
                self._function_types[-1].calls.append(
                    (caller, func.value.id, func.attr, node.lineno)
                )
            constructed = (
                _constructed_class(func.value)
                if isinstance(func, ast.Attribute)
                else None
            )
            if constructed is not None:  # `Cls(...).method()`
                self.typed_calls.append(
                    {
                        "caller": caller,
                        "class": constructed,
                        "method": func.attr,
                        "line": node.lineno,
                    }
                )
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
                        "object": _dotted_name(node.value),
                        "attribute": node.attr,
                        "line": node.lineno,
                    }
                )
        self.generic_visit(node)

    def visit_Name(self, node):
        if (
            self._function_types
            and not isinstance(node.ctx, ast.Load)
            and id(node) not in self._typed_targets
        ):
            self._function_types[-1].assign(node.id, _FunctionTypes.UNTYPED)
        # A read in a class body belongs to the class, which has no caller.
        referrer = self.callers[-1] if self.callers else self.scopes[-1]
        if (self.callers or self.class_scopes) and isinstance(node.ctx, ast.Load):
            self.name_loads.append(
                {"referrer": referrer, "name": node.id, "line": node.lineno}
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
            "typed_calls": [],
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
        "typed_calls": collector.typed_calls,
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


def extract_typed_method_calls(path: str, source: str) -> list[dict]:
    return _collect(path, _parse_or_none(path, source)).typed_calls


def extract_foreign_attribute_accesses(path: str, source: str) -> list[dict]:
    return _collect(path, _parse_or_none(path, source)).foreign_accesses


def extract_name_loads(path: str, source: str) -> list[dict]:
    return _collect(path, _parse_or_none(path, source)).name_loads
