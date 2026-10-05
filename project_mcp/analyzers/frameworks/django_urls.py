"""Django URL routing — named URL patterns in urls.py and the views they route to."""

import ast
from pathlib import Path

URL_PATTERN_FUNCTIONS = {"path", "re_path", "url"}
URL_REVERSE_FUNCTIONS = {"reverse", "reverse_lazy"}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _argument(node: ast.Call, position: int, keyword: str) -> ast.expr | None:
    """A call argument given either positionally or by keyword."""
    if len(node.args) > position:
        return node.args[position]
    return next((kw.value for kw in node.keywords if kw.arg == keyword), None)


def _string(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _view_expression(node: ast.expr) -> str | None:
    """The view as written, with a class-based view's `.as_view(...)` dropped."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "as_view"
    ):
        node = node.func.value
    return _dotted(node)


def _include(node: ast.Call) -> dict | None:
    """`include("pkg.urls", namespace=...)` or `include(("pkg.urls", "app"))`."""
    if not node.args:
        return None
    target, app_name = node.args[0], None
    if isinstance(target, ast.Tuple) and len(target.elts) == 2:
        target, app_name = target.elts[0], _string(target.elts[1])
    module = _string(target)
    if module is None:
        return None
    namespace = next(
        (_string(kw.value) for kw in node.keywords if kw.arg == "namespace"), None
    )
    return {"module": module, "app_name": app_name, "namespace": namespace}


def extract_url_patterns(source: str) -> dict:
    """The module's `app_name`, each named `path()` with its view, and its includes."""
    tree = ast.parse(source)
    app_name = None
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "app_name"
            for target in statement.targets
        ):
            app_name = _string(statement.value) or app_name

    patterns = []
    includes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node) == "include":
            included = _include(node)
            if included:
                includes.append(included)
            continue
        if _call_name(node) not in URL_PATTERN_FUNCTIONS:
            continue
        name = next(
            (_string(kw.value) for kw in node.keywords if kw.arg == "name"), None
        )
        view = _view_expression(_argument(node, 1, "view"))
        if name and view:
            patterns.append({"name": name, "view": view})
    return {"app_name": app_name, "patterns": patterns, "includes": includes}


class _ReverseCollector(ast.NodeVisitor):
    def __init__(self, module: str):
        self.scope = [module]
        self.reverses: list[dict] = []

    def _visit_scope(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _visit_scope

    def visit_Call(self, node: ast.Call):
        url_name = _string(_argument(node, 0, "viewname"))
        if _call_name(node) in URL_REVERSE_FUNCTIONS and url_name:
            self.reverses.append({"caller": ".".join(self.scope), "url_name": url_name})
        self.generic_visit(node)


def extract_url_reverses(path: str, source: str) -> list[dict]:
    """Each `reverse("ns:name")` call with a literal name, and the scope making it."""
    collector = _ReverseCollector(".".join(Path(path).with_suffix("").parts))
    collector.visit(ast.parse(source))
    return collector.reverses
