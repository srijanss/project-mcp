from pathlib import Path

from project_mcp.plugins.python.dependencies import (
    declared_dependencies,
    normalize_dependency_name,
    python_dependency,
    resolved_versions,
)
from project_mcp.plugins.registry import PluginRegistry, builtin_registry


def list_dependencies(
    project_root: Path,
    ecosystem: str | None = None,
    registry: PluginRegistry | None = None,
) -> list[dict]:
    """The dependencies each language plugin reads from its manifests.

    `ecosystem` keeps only the plugin of that ecosystem.
    """
    if registry is None:
        registry = builtin_registry()
    result = []
    for descriptor in registry.language_descriptors():
        if descriptor.ecosystem is None or ecosystem not in (None, descriptor.ecosystem):
            continue
        language = next(iter(descriptor.extensions.values()))
        reader = getattr(registry.analyzer_for(language), "list_dependencies", None)
        if callable(reader):
            result.extend(reader(Path(project_root)))
    return result


def get_dependency_version(
    project_root: Path, name: str, ecosystem: str | None = None
) -> dict:
    for dependency in list_dependencies(project_root, ecosystem):
        if dependency["ecosystem"] == "python":
            matches = normalize_dependency_name(dependency["name"]) == normalize_dependency_name(name)
        else:
            matches = dependency["name"] == name
        if matches:
            return dependency
    root = Path(project_root)
    if not declared_dependencies(root) and ecosystem in (None, "python"):
        version = resolved_versions(root).get(normalize_dependency_name(name))
        if version:
            return python_dependency(name, version, "resolved")
    return {"status": "not_found"}
