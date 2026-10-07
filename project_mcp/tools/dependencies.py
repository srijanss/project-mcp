from pathlib import Path

from project_mcp.plugins.registry import PluginRegistry, builtin_registry


def _ecosystem_analyzers(registry: PluginRegistry, ecosystem: str | None) -> dict:
    """The analyzer of each language plugin's ecosystem, or only of `ecosystem`."""
    analyzers = {}
    for descriptor in registry.language_descriptors():
        if descriptor.ecosystem is None or ecosystem not in (None, descriptor.ecosystem):
            continue
        language = next(iter(descriptor.extensions.values()))
        analyzers[descriptor.ecosystem] = registry.analyzer_for(language)
    return analyzers


def read_dependencies(
    project_root: Path, ecosystem: str | None, registry: PluginRegistry
) -> tuple[list[dict], dict[str, ValueError]]:
    """The dependencies each language plugin reads from its manifests, and
    the error of each ecosystem whose manifests cannot be read."""
    result = []
    errors: dict[str, ValueError] = {}
    for name, analyzer in _ecosystem_analyzers(registry, ecosystem).items():
        reader = getattr(analyzer, "list_dependencies", None)
        if not callable(reader):
            continue
        try:
            result.extend(reader(Path(project_root)))
        except ValueError as exc:
            errors[name] = exc
    return result, errors


def list_dependencies(
    project_root: Path,
    ecosystem: str | None = None,
    registry: PluginRegistry | None = None,
) -> list[dict]:
    """The dependencies each language plugin reads from its manifests.

    `ecosystem` keeps only the plugin of that ecosystem. A manifest that
    cannot be read is reported as `{"ecosystem", "error"}` beside the other
    ecosystems' dependencies, and raised when there are none.
    """
    if registry is None:
        registry = builtin_registry()
    result, errors = read_dependencies(project_root, ecosystem, registry)
    if errors and not result:
        raise next(iter(errors.values()))
    return result + [{"ecosystem": name, "error": str(exc)} for name, exc in errors.items()]


def matching_dependency(
    dependencies: list[dict], name: str, registry: PluginRegistry
) -> dict | None:
    """The first of `dependencies` named `name`, as its plugin's
    `dependency_key` compares names (exactly, when it has none)."""
    analyzers = _ecosystem_analyzers(registry, None)
    for dependency in dependencies:
        if "error" in dependency:
            continue
        key = getattr(analyzers.get(dependency["ecosystem"]), "dependency_key", None)
        if not callable(key):
            key = str
        if key(dependency["name"]) == key(name):
            return dependency
    return None


def get_dependency_version(
    project_root: Path,
    name: str,
    ecosystem: str | None = None,
    registry: PluginRegistry | None = None,
) -> dict:
    if registry is None:
        registry = builtin_registry()
    dependencies = list_dependencies(project_root, ecosystem, registry)
    dependency = matching_dependency(dependencies, name, registry)
    if dependency is not None:
        return dependency
    for analyzer in _ecosystem_analyzers(registry, ecosystem).values():
        undeclared = getattr(analyzer, "undeclared_dependency", None)
        if callable(undeclared) and (found := undeclared(Path(project_root), name)):
            return found
    errors = [dependency for dependency in dependencies if "error" in dependency]
    return {"status": "not_found", **({"manifest_errors": errors} if errors else {})}
