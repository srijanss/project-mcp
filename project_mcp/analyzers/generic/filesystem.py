import os
from pathlib import Path

from project_mcp.config import ProjectConfig
from project_mcp.ignore import should_exclude

ALWAYS_EXCLUDED_DIRS = {".project-mcp"}

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".toml": "toml",
    ".cfg": "ini",
    ".ini": "ini",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".md": "markdown",
    ".rst": "restructuredtext",
    ".rs": "rust",
}

JS_LANGUAGES = {"javascript", "typescript"}

DOCS_LANGUAGES = {"markdown", "restructuredtext"}
CONFIG_LANGUAGES = {"toml", "ini", "yaml", "json"}


def _is_test_path(path: Path) -> bool:
    if "tests" in path.parts[:-1] or "test" in path.parts[:-1]:
        return True
    stem = path.stem
    return stem.startswith("test_") or stem.endswith("_test")


def _is_js_test_path(path: Path) -> bool:
    if "tests" in path.parts[:-1] or "__tests__" in path.parts[:-1]:
        return True
    stem = path.stem
    return stem.endswith(".test") or stem.endswith(".spec")


def classify_file(path: Path) -> dict:
    path = Path(path)
    language = LANGUAGE_BY_EXTENSION.get(path.suffix)

    if language == "python" and _is_test_path(path):
        file_kind = "test"
    elif language in JS_LANGUAGES and _is_js_test_path(path):
        file_kind = "test"
    elif language == "rust" and ("tests" in path.parts[:-1] or _is_test_path(path)):
        file_kind = "test"
    elif language in CONFIG_LANGUAGES:
        file_kind = "config"
    elif language in DOCS_LANGUAGES:
        file_kind = "docs"
    else:
        file_kind = "source"

    return {"language": language, "file_kind": file_kind}


def _is_excluded_dir(dir_path: Path, project_root: Path, config: ProjectConfig) -> bool:
    relative_dir = dir_path.relative_to(project_root)
    if relative_dir.parts[0] in ALWAYS_EXCLUDED_DIRS:
        return True
    return should_exclude(relative_dir, config)


def discover_files(project_root: Path, config: ProjectConfig) -> list[dict]:
    project_root = Path(project_root)
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

            relative_path = path.relative_to(project_root)
            if should_exclude(relative_path, config):
                continue

            classification = classify_file(relative_path)
            stat = path.stat()
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
