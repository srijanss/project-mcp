import tomllib
from pathlib import Path


def _load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid {path.name}") from exc


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


def list_rust_dependencies(project_root: Path) -> list[dict]:
    """Cargo.toml dependencies, at their Cargo.lock version when it pins one."""
    resolved_cargo = _resolved_cargo_versions(project_root)
    result = []
    for dependency in _declared_cargo_dependencies(project_root):
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
