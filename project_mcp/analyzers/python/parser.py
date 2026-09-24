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
    module_name = _module_qualified_name(path)
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [{"kind": "parse_error", "path": path, "error": str(exc)}]

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
            elif in_class and isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    symbols.append(
                        {
                            "name": target.id,
                            "qualified_name": f"{qualified_prefix}.{target.id}",
                            "kind": "field",
                            "start_line": node.lineno,
                            "end_line": node.end_lineno,
                            "visibility": _visibility(target.id),
                        }
                    )

    visit_body(tree.body, module_name, in_class=False)
    return symbols


def extract_imports(path: str, source: str) -> list[dict]:
    tree = ast.parse(source, filename=path)
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(
                    {
                        "module": alias.name,
                        "names": [],
                        "level": 0,
                        "line": node.lineno,
                    }
                )
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
            imports.append(record)

    return imports


def extract_static_calls(path: str, source: str) -> list[dict]:
    module_name = _module_qualified_name(path)
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []

    calls = []

    class CallVisitor(ast.NodeVisitor):
        def __init__(self):
            self.callers = []
            self.scopes = [module_name]

        def visit_ClassDef(self, node):
            self.scopes.append(f"{self.scopes[-1]}.{node.name}")
            self.generic_visit(node)
            self.scopes.pop()

        def visit_FunctionDef(self, node):
            prefix = self.callers[-1] if self.callers else self.scopes[-1]
            self.callers.append(f"{prefix}.{node.name}")
            self.generic_visit(node)
            self.callers.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node):
            if self.callers and isinstance(node.func, ast.Name):
                calls.append(
                    {
                        "caller": self.callers[-1],
                        "callee": node.func.id,
                        "line": node.lineno,
                    }
                )
            self.generic_visit(node)

    CallVisitor().visit(tree)
    return calls


def extract_self_attribute_references(path: str, source: str) -> list[dict]:
    module_name = _module_qualified_name(path)
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []

    references = []

    class ReferenceVisitor(ast.NodeVisitor):
        def __init__(self):
            self.callers = []
            self.scopes = [module_name]
            self.class_scopes = []

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

        def visit_Attribute(self, node):
            if (
                self.callers
                and self.class_scopes
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
            ):
                references.append(
                    {
                        "referrer": self.callers[-1],
                        "class": self.class_scopes[-1],
                        "attribute": node.attr,
                        "line": node.lineno,
                    }
                )
            self.generic_visit(node)

    ReferenceVisitor().visit(tree)
    return references
