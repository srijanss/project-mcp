import ast
from pathlib import Path

from project_mcp.plugins.registry import builtin_registry

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "project_mcp"

# Modules a plugin owns: everything in its own package.
PLUGIN_PACKAGES = (
    "project_mcp.plugins.python",
    "project_mcp.plugins.javascript",
    "project_mcp.plugins.rust",
    "project_mcp.plugins.django",
    "project_mcp.plugins.astro",
    "project_mcp.plugins.react",
)


def _module_name(path: Path) -> str:
    parts = path.relative_to(PACKAGE_ROOT.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _is_plugin_module(name: str) -> bool:
    return any(name == package or name.startswith(package + ".") for package in PLUGIN_PACKAGES)


def _core_modules():
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        name = _module_name(path)
        if not _is_plugin_module(name):
            yield path, name, ast.parse(path.read_text())


def _imported_modules(tree: ast.Module, module: str, is_package: bool) -> set[str]:
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = module.split(".")
                parent = parent[: len(parent) - node.level + (1 if is_package else 0)]
                base = ".".join([*parent, base] if base else parent)
            imported.add(base)
            imported.update(f"{base}.{alias.name}" for alias in node.names)
    return imported


def _plugin_names() -> set[str]:
    registry = builtin_registry()
    names = set(registry.plugin_names())
    for descriptor in registry.language_descriptors():
        names.update(descriptor.extensions.values())
        if descriptor.ecosystem:
            names.add(descriptor.ecosystem)
    return names


def _name_comparisons(tree: ast.Module, names: set[str]) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        for operand in operands:
            constants = operand.elts if isinstance(operand, (ast.Tuple, ast.List, ast.Set)) else [operand]
            for constant in constants:
                if isinstance(constant, ast.Constant) and constant.value in names:
                    found.append(f"line {node.lineno}: {ast.unparse(node)}")
    return found


def test_core_never_imports_a_plugin_module():
    violations = [
        f"{name} imports {imported}"
        for path, name, tree in _core_modules()
        for imported in sorted(_imported_modules(tree, name, path.name == "__init__.py"))
        if _is_plugin_module(imported)
    ]

    assert violations == []


def test_core_never_branches_on_a_plugin_language_or_ecosystem_name():
    names = _plugin_names()

    violations = [
        f"{name} {comparison}"
        for _, name, tree in _core_modules()
        for comparison in _name_comparisons(tree, names)
    ]

    assert violations == []
