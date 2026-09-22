import re
import tomllib
from pathlib import Path


_REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?(.*)$")


def normalize_dependency_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid {path.name}") from exc


def _dependency(name: str, version: str | None, status: str) -> dict:
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
    return _dependency(match.group(1), match.group(2) or None, "declared")


def _declared_dependencies(project_root: Path) -> list[dict]:
    dependencies = []
    pyproject = project_root / "pyproject.toml"
    if pyproject.is_file():
        project = _load_toml(pyproject).get("project", {})
        for requirement in project.get("dependencies", []):
            parsed = _parse_requirement(requirement)
            if parsed:
                dependencies.append(parsed)

    seen_files = set()

    def read_requirements(requirements_file: Path) -> None:
        resolved_file = requirements_file.resolve()
        if resolved_file in seen_files or not requirements_file.is_file():
            return
        seen_files.add(resolved_file)
        for line in requirements_file.read_text().splitlines():
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


def _resolved_versions(project_root: Path) -> dict[str, str]:
    lockfile = project_root / "uv.lock"
    if not lockfile.is_file():
        return {}
    packages = _load_toml(lockfile).get("package", [])
    return {
        normalize_dependency_name(package["name"]): package["version"]
        for package in packages
        if "name" in package and "version" in package
    }


def _declared_cargo_dependencies(project_root: Path) -> list[dict]:
    dependencies = []
    cargo_toml = project_root / "Cargo.toml"
    if not cargo_toml.is_file():
        return dependencies

    for name, spec in _load_toml(cargo_toml).get("dependencies", {}).items():
        if isinstance(spec, str):
            version = spec
        elif isinstance(spec, dict):
            version = spec.get("version")
        else:
            version = None
        dependencies.append(
            {
                "name": name,
                "ecosystem": "rust",
                "version": version,
                "version_status": "unknown" if version is None else "declared",
            }
        )
    return dependencies


def _resolved_cargo_versions(project_root: Path) -> dict[str, str]:
    lockfile = project_root / "Cargo.lock"
    if not lockfile.is_file():
        return {}
    packages = _load_toml(lockfile).get("package", [])
    return {
        package["name"]: package["version"]
        for package in packages
        if "name" in package and "version" in package
    }


def list_dependencies(project_root: Path, ecosystem: str | None = None) -> list[dict]:
    if ecosystem not in (None, "python", "rust"):
        return []

    root = Path(project_root)
    result = []

    if ecosystem in (None, "python"):
        resolved = _resolved_versions(root)
        seen = set()
        for dependency in _declared_dependencies(root):
            name = dependency["name"]
            normalized_name = normalize_dependency_name(name)
            if normalized_name in seen:
                continue
            seen.add(normalized_name)
            if normalized_name in resolved:
                result.append(_dependency(name, resolved[normalized_name], "resolved"))
            else:
                result.append(dependency)

    if ecosystem in (None, "rust"):
        resolved_cargo = _resolved_cargo_versions(root)
        for dependency in _declared_cargo_dependencies(root):
            name = dependency["name"]
            if name in resolved_cargo:
                result.append(
                    {
                        "name": name,
                        "ecosystem": "rust",
                        "version": resolved_cargo[name],
                        "version_status": "resolved",
                    }
                )
            else:
                result.append(dependency)

    return result


def get_dependency_version(
    project_root: Path, name: str, ecosystem: str | None = None
) -> dict:
    for dependency in list_dependencies(project_root, ecosystem):
        if normalize_dependency_name(dependency["name"]) == normalize_dependency_name(name):
            return dependency
    root = Path(project_root)
    if not _declared_dependencies(root) and ecosystem in (None, "python"):
        version = _resolved_versions(root).get(normalize_dependency_name(name))
        if version:
            return _dependency(name, version, "resolved")
    return {"status": "not_found"}
