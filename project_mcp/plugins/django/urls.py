"""Django URL routing — named URL patterns in urls.py and the views they route to."""

import ast
from pathlib import Path

URL_PATTERN_FUNCTIONS = {"path", "re_path", "url"}
URL_REVERSE_FUNCTIONS = {"reverse", "reverse_lazy"}
REQUEST_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace", "generic"}


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
        # Per scope, the url names each variable was assigned the reverse of.
        self.urls: list[dict[str, list[str]]] = [{}]
        # Per class, the same for the `self.x` its body or methods assign.
        self.self_urls: list[dict[str, list[str]]] = [{}]

    def _visit_scope(self, node):
        self.scope.append(node.name)
        self.urls.append({})
        self.generic_visit(node)
        self.urls.pop()
        self.scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _visit_scope

    def visit_ClassDef(self, node: ast.ClassDef):
        self.self_urls.append(_self_urls(node))
        self._visit_scope(node)
        self.self_urls.pop()

    def visit_Assign(self, node: ast.Assign):
        url_names = self._reversed_names(node.value)
        for target in node.targets:
            if url_names and isinstance(target, ast.Name):
                self.urls[-1][target.id] = url_names
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        url = _argument(node, 0, "path") if _is_request(node) else None
        for url_name in self._reversed_names(url):
            self.reverses.append({"caller": ".".join(self.scope), "url_name": url_name})
        self.generic_visit(node)

    def _reversed_names(self, node: ast.expr | None) -> list[str]:
        """The literal url names reversed in an expression, directly or
        through a variable holding a reversed url."""
        if node is None:
            return []
        names = []
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                # The function's own variable, else the module's.
                for urls in (self.urls[-1], self.urls[0]):
                    if child.id in urls:
                        names.extend(urls[child.id])
                        break
            elif isinstance(child, ast.Attribute):
                names.extend(self.self_urls[-1].get(_dotted(child) or "", []))
        return names + _literal_reverses(node)


def _self_urls(node: ast.ClassDef) -> dict[str, list[str]]:
    """The url names a class reverses onto `self.x`: as class attributes, or
    in any method (read up front, since setUp may sit below the tests)."""
    self_urls = {}
    for statement in node.body:
        for assign in ast.walk(statement):
            if not isinstance(assign, ast.Assign):
                continue
            url_names = _literal_reverses(assign.value)
            for target in assign.targets:
                if isinstance(target, ast.Name) and assign is statement:
                    name = f"self.{target.id}"
                else:
                    name = _dotted(target) or ""
                if url_names and name.startswith("self."):
                    self_urls[name] = url_names
    return self_urls


def _literal_reverses(node: ast.expr) -> list[str]:
    """The literal url names `reverse(...)` calls in an expression reverse."""
    return [
        url_name
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and _call_name(call) in URL_REVERSE_FUNCTIONS
        and (url_name := _string(_argument(call, 0, "viewname")))
    ]


def _is_request(node: ast.Call) -> bool:
    """`client.get(...)`, `self.client.post(...)`, `rf.get(...)` and the like."""
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr in REQUEST_METHODS):
        return False
    receiver = (_dotted(func.value) or "").rsplit(".", 1)[-1].lower()
    return receiver == "rf" or receiver.endswith(("client", "factory"))


def extract_url_reverses(path: str, source: str) -> list[dict]:
    """Each `reverse("ns:name")` with a literal name whose url a test client
    requests, and the scope making the request."""
    collector = _ReverseCollector(".".join(Path(path).with_suffix("").parts))
    collector.visit(ast.parse(source))
    return collector.reverses
