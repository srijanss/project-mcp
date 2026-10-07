import os
from pathlib import Path

from project_mcp.config import ProjectConfig
from project_mcp.ignore import should_exclude
from project_mcp.plugins.registry import PluginRegistry, builtin_registry

ALWAYS_EXCLUDED_DIRS = {".project-mcp"}


def classify_file(path: Path, registry: PluginRegistry | None = None) -> dict:
    path = Path(path)
    if registry is None:
        registry = builtin_registry()
    language = registry.language_for(path)
    analyzer = registry.analyzer_for(language)

    if analyzer is not None and analyzer.is_test_file(path):
        file_kind = "test"
    else:
        file_kind = registry.file_kind_for(path)

    return {"language": language, "file_kind": file_kind}


def _is_binary(path: Path) -> bool:
    with open(path, "rb") as handle:
        return b"\0" in handle.read(8192)


def _is_excluded_dir(dir_path: Path, project_root: Path, config: ProjectConfig) -> bool:
    relative_dir = dir_path.relative_to(project_root)
    if relative_dir.parts[0] in ALWAYS_EXCLUDED_DIRS:
        return True
    return should_exclude(relative_dir, config)


def discover_files(
    project_root: Path, config: ProjectConfig, registry: PluginRegistry | None = None
) -> list[dict]:
    project_root = Path(project_root)
    if registry is None:
        registry = builtin_registry()
    resolved_root = project_root.resolve()
    records = []

    for dirpath, dirnames, filenames in os.walk(project_root):
        current_dir = Path(dirpath)
        dirnames[:] = [
            name
            for name in dirnames
            if not _is_excluded_dir(current_dir / name, project_root, config)
        ]

        for filename in filenames:
            path = current_dir / filename
            if not path.is_file():
                continue
            if path.is_symlink() and not path.resolve().is_relative_to(resolved_root):
                continue  # never index a file outside the project through a link

            relative_path = path.relative_to(project_root)
            if should_exclude(relative_path, config):
                continue
            try:
                stat = path.stat()
                if stat.st_size > config.max_file_bytes or _is_binary(path):
                    continue
            except OSError:
                continue  # unreadable, or removed since the directory was listed

            classification = classify_file(relative_path, registry)
            records.append(
                {
                    "path": relative_path.as_posix(),
                    "language": classification["language"],
                    "file_kind": classification["file_kind"],
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )

    records.sort(key=lambda record: record["path"])
    return records
