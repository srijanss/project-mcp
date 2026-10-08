import json
from pathlib import Path


def _read_manifest(path: Path) -> str:
    try:
        return path.read_text()
    except OSError as exc:
        raise ValueError(f"unreadable {path.name}") from exc


def _load_json(path: Path) -> dict:
    try:
        return json.loads(_read_manifest(path))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {path.name}") from exc


def _declared_npm_dependencies(project_root: Path) -> list[dict]:
    dependencies = []
    package_json = project_root / "package.json"
    if not package_json.is_file():
        return dependencies

    manifest = _load_json(package_json)
    for name, version in manifest.get("dependencies", {}).items():
        dependencies.append(
            {
                "name": name,
                "ecosystem": "npm",
                "version": version,
                "version_status": "unknown" if not version else "declared",
            }
        )
    return dependencies


def _resolved_npm_versions(project_root: Path) -> dict[str, str]:
    lockfile = project_root / "package-lock.json"
    if not lockfile.is_file():
        return {}
    packages = _load_json(lockfile).get("packages", {})
    resolved = {}
    for path, info in packages.items():
        if not path.startswith("node_modules/"):
            continue
        name = path.rsplit("node_modules/", 1)[-1]
        if "version" in info:
            resolved[name] = info["version"]
    return resolved


def list_npm_dependencies(project_root: Path) -> list[dict]:
    """package.json dependencies, at their package-lock.json version when it pins one."""
    resolved_npm = _resolved_npm_versions(project_root)
    result = []
    for dependency in _declared_npm_dependencies(project_root):
        name = dependency["name"]
        if name in resolved_npm:
            result.append(
                {
                    "name": name,
                    "ecosystem": "npm",
                    "version": resolved_npm[name],
                    "version_status": "resolved",
                }
            )
        else:
            result.append(dependency)
    return result
