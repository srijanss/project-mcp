import re
import tomllib
from pathlib import Path


_REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?(.*)$")


def normalize_dependency_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_manifest(path: Path) -> str:
    try:
        return path.read_text()
    except OSError as exc:
        raise ValueError(f"unreadable {path.name}") from exc


def _load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(_read_manifest(path))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid {path.name}") from exc


def python_dependency(name: str, version: str | None, status: str) -> dict:
    if version and version.startswith("=="):
        version = version[2:]
    return {
        "name": name,
        "ecosystem": "python",
        "version": version,
        "version_status": "unknown" if version is None else status,
    }


def _parse_requirement(requirement: str) -> dict | None:
    requirement = requirement.split("#", 1)[0].strip()
    if not requirement or requirement.startswith(("#", "-")):
        return None
    if "@" in requirement:
        return None
    requirement = requirement.split(";", 1)[0].split(" --", 1)[0].strip()
    match = _REQUIREMENT.match(requirement)
    if match is None:
        return None
    return python_dependency(match.group(1), match.group(2) or None, "declared")


def declared_dependencies(project_root: Path) -> list[dict]:
    dependencies = []
    pyproject = project_root / "pyproject.toml"
    if pyproject.is_file():
        project = _load_toml(pyproject).get("project", {})
        for requirement in project.get("dependencies", []):
            parsed = _parse_requirement(requirement)
            if parsed:
                dependencies.append(parsed)

    seen_files = set()
    root = project_root.resolve()

    def read_requirements(requirements_file: Path) -> None:
        # An include never reads a file outside the project.
        resolved_file = requirements_file.resolve()
        if (
            not resolved_file.is_relative_to(root)
            or resolved_file in seen_files
            or not requirements_file.is_file()
        ):
            return
        seen_files.add(resolved_file)
        for line in _read_manifest(requirements_file).splitlines():
            stripped = line.strip()
            if stripped.startswith(("-r ", "--requirement ")):
                read_requirements(requirements_file.parent / stripped.split(maxsplit=1)[1])
                continue
            parsed = _parse_requirement(line)
            if parsed:
                dependencies.append(parsed)

    for requirements_file in sorted(project_root.glob("requirements*.txt")):
        read_requirements(requirements_file)
    return dependencies


def resolved_versions(project_root: Path) -> dict[str, str]:
    lockfile = project_root / "uv.lock"
    if not lockfile.is_file():
        return {}
    packages = _load_toml(lockfile).get("package", [])
    return {
        normalize_dependency_name(package["name"]): package["version"]
        for package in packages
        if "name" in package and "version" in package
    }


def list_python_dependencies(project_root: Path) -> list[dict]:
    """Declared dependencies, at their uv.lock version when it pins one."""
    resolved = resolved_versions(project_root)
    result = []
    seen = set()
    for dependency in declared_dependencies(project_root):
        name = dependency["name"]
        normalized_name = normalize_dependency_name(name)
        if normalized_name in seen:
            continue
        seen.add(normalized_name)
        if normalized_name in resolved:
            result.append(python_dependency(name, resolved[normalized_name], "resolved"))
        else:
            result.append(dependency)
    return result
