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

    def _visit_scope(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _visit_scope

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


def extract_mock_patches(path: str, source: str) -> list[dict]:
    """Each literal `patch("pkg.module.Name")` or `patch.object(obj, "name")`,
    with the test it is in force for."""
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
    return patches
