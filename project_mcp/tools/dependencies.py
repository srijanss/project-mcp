import re
import tomllib
from pathlib import Path


_REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?(.*)$")


def _normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _dependency(name: str, version: str | None, status: str) -> dict:
    if version and version.startswith("=="):
        version = version[2:]
    return {
        "name": name,
        "ecosystem": "python",
        "version": version,
        "version_status": status,
    }


def _parse_requirement(requirement: str) -> dict | None:
    requirement = requirement.strip()
    if not requirement or requirement.startswith(("#", "-")):
        return None
    if " @ " in requirement:
        return None
    match = _REQUIREMENT.match(requirement)
    if match is None:
        return None
    return _dependency(match.group(1), match.group(2) or None, "declared")


def _declared_dependencies(project_root: Path) -> list[dict]:
    dependencies = []
    pyproject = project_root / "pyproject.toml"
    if pyproject.is_file():
        project = tomllib.loads(pyproject.read_text()).get("project", {})
        for requirement in project.get("dependencies", []):
            parsed = _parse_requirement(requirement)
            if parsed:
                dependencies.append(parsed)

    for requirements_file in sorted(project_root.glob("requirements*.txt")):
        for line in requirements_file.read_text().splitlines():
            parsed = _parse_requirement(line)
            if parsed:
                dependencies.append(parsed)
    return dependencies


def _resolved_versions(project_root: Path) -> dict[str, str]:
    lockfile = project_root / "uv.lock"
    if not lockfile.is_file():
        return {}
    packages = tomllib.loads(lockfile.read_text()).get("package", [])
    return {
        _normalized_name(package["name"]): package["version"]
        for package in packages
        if "name" in package and "version" in package
    }


def list_dependencies(project_root: Path, ecosystem: str | None = None) -> list[dict]:
    if ecosystem not in (None, "python"):
        return []

    root = Path(project_root)
    resolved = _resolved_versions(root)
    seen = set()
    result = []
    for dependency in _declared_dependencies(root):
        name = dependency["name"]
        normalized_name = _normalized_name(name)
        if normalized_name in seen:
            continue
        seen.add(normalized_name)
        if normalized_name in resolved:
            result.append(_dependency(name, resolved[normalized_name], "resolved"))
        else:
            result.append(dependency)
    return result


def get_dependency_version(
    project_root: Path, name: str, ecosystem: str | None = None
) -> dict:
    for dependency in list_dependencies(project_root, ecosystem):
        if _normalized_name(dependency["name"]) == _normalized_name(name):
            return dependency
    root = Path(project_root)
    if not _declared_dependencies(root) and ecosystem in (None, "python"):
        version = _resolved_versions(root).get(_normalized_name(name))
        if version:
            return _dependency(name, version, "resolved")
    return {"status": "not_found"}
