"""Mock patches in tests — the names `patch(...)` replaces while a test runs."""

import ast
from pathlib import Path

# Methods run before each (or all) of a class's tests: a patch they start is
# in force for those tests.
SETUP_METHODS = {"setUp", "setUpClass", "setUpTestData", "setup_method", "setup_class"}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


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


def _fixture_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.expr | None:
    """Its `@pytest.fixture`, `@fixture` or `@pytest.fixture(...)` decorator."""
    for decorator in node.decorator_list:
        func = decorator.func if isinstance(decorator, ast.Call) else decorator
        if (_dotted(func) or "").rsplit(".", 1)[-1] == "fixture":
            return decorator
    return None


def _is_autouse(decorator: ast.expr) -> bool:
    return isinstance(decorator, ast.Call) and any(
        kw.arg == "autouse" and isinstance(kw.value, ast.Constant) and kw.value.value is True
        for kw in decorator.keywords
    )


def _is_patch_object(node: ast.Call) -> bool:
    """`patch.object(...)`, however `patch` itself was reached."""
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "object"):
        return False
    return (_dotted(func.value) or "").rsplit(".", 1)[-1] == "patch"


class _PatchCollector(ast.NodeVisitor):
    def __init__(self, module: str):
        self.scope = [module]
        self.patches: list[dict] = []
        self.class_tests: dict[str, list[str]] = {}
        # Fixture name -> its scope, the autouse fixtures' scopes, and each
        # function's parameter names.
        self.fixtures: dict[str, str] = {}
        self.autouse: list[str] = []
        self.parameters: dict[str, list[str]] = {}

    def _visit_scope(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        scope = ".".join([*self.scope, node.name])
        decorator = _fixture_decorator(node)
        if decorator is not None:
            self.fixtures[node.name] = scope
            if _is_autouse(decorator):
                self.autouse.append(scope)
        self.parameters[scope] = [arg.arg for arg in node.args.args]
        self._visit_scope(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef):
        scope = ".".join([*self.scope, node.name])
        methods = [
            item.name
            for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        tests = [f"{scope}.{name}" for name in methods if name.startswith("test")]
        self.class_tests[scope] = tests
        for name in SETUP_METHODS.intersection(methods):
            self.class_tests[f"{scope}.{name}"] = tests
        self._visit_scope(node)

    def visit_Call(self, node: ast.Call):
        caller = ".".join(self.scope)
        if _is_patch_object(node) and len(node.args) >= 2:
            obj, attribute = _dotted(node.args[0]), _string(node.args[1])
            if obj and attribute:
                self.patches.append(
                    {"caller": caller, "object": obj, "attribute": attribute}
                )
        elif _call_name(node) == "patch" and node.args:
            target = _string(node.args[0])
            if target:
                self.patches.append({"caller": caller, "target": target})
        self.generic_visit(node)


def extract_mock_patches(
    path: str, source: str, outer_fixtures: dict[str, dict] | None = None
) -> list[dict]:
    """Each literal `patch("pkg.module.Name")` or `patch.object(obj, "name")`,
    with the test it is in force for.

    `outer_fixtures` are those conftest.py files give the module, as
    `extract_fixture_patches` reads them.
    """
    outer_fixtures = outer_fixtures or {}
    collector = _PatchCollector(".".join(Path(path).with_suffix("").parts))
    collector.visit(ast.parse(source))
    # A patch on a class (its decorator) or started in its setup is in force
    # for each of its tests.
    patches = []
    for patch in collector.patches:
        tests = collector.class_tests.get(patch["caller"])
        if tests is None:
            patches.append(patch)
        else:
            patches.extend({**patch, "caller": test} for test in tests)
    # A patch a fixture makes is in force for each test requesting it, and
    # an autouse fixture's for each test in the module or class defining it.
    fixture_scopes = set(collector.fixtures.values())
    by_caller: dict[str, list[dict]] = {}
    for patch in patches:
        by_caller.setdefault(patch["caller"], []).append(patch)
    in_force = [patch for patch in patches if patch["caller"] not in fixture_scopes]
    for test, parameters in collector.parameters.items():
        if test in fixture_scopes or not test.rsplit(".", 1)[-1].startswith("test"):
            continue
        autouse = [
            fixture
            for fixture in collector.autouse
            if test.startswith(f"{fixture.rsplit('.', 1)[0]}.")
        ]
        closure = _fixture_closure(collector, autouse, parameters)
        for fixture in closure:
            for patch in by_caller.get(fixture, []):
                in_force.append({**patch, "caller": test})
        # Fixtures the module doesn't define come from its conftest.py files.
        requested = [
            *(name for name, fixture in outer_fixtures.items() if fixture["autouse"]),
            *parameters,
            *(name for fixture in closure for name in collector.parameters[fixture]),
        ]
        for name in dict.fromkeys(requested):
            if name in collector.fixtures or name not in outer_fixtures:
                continue
            for patch in outer_fixtures[name]["patches"]:
                in_force.append({**patch, "caller": test})
    return in_force


def extract_fixture_patches(path: str, source: str) -> dict[str, dict]:
    """Each fixture (as in a conftest.py), whether it is autouse, and the
    patches it and the fixtures it requests put in force."""
    collector = _PatchCollector(".".join(Path(path).with_suffix("").parts))
    collector.visit(ast.parse(source))
    fixtures = {}
    for name, scope in collector.fixtures.items():
        patches = [
            {key: value for key, value in patch.items() if key != "caller"}
            for fixture in _fixture_closure(collector, [scope], [])
            for patch in collector.patches
            if patch["caller"] == fixture
        ]
        fixtures[name] = {"autouse": scope in collector.autouse, "patches": patches}
    return fixtures


def _fixture_closure(
    collector: _PatchCollector, fixtures: list[str], requested: list[str]
) -> list[str]:
    """The fixtures given, those requested by name, and those they request."""
    closure = list(dict.fromkeys(fixtures))
    pending = list(requested)
    for fixture in closure:
        pending += collector.parameters[fixture]
    while pending:
        fixture = collector.fixtures.get(pending.pop(0))
        if fixture is not None and fixture not in closure:
            closure.append(fixture)
            pending += collector.parameters[fixture]
    return closure
