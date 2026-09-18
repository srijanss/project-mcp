from pathlib import Path

from project_mcp.config import ProjectConfig
from project_mcp.ignore import should_exclude

ALWAYS_EXCLUDED_DIRS = {".project-mcp"}

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".toml": "toml",
    ".cfg": "ini",
    ".ini": "ini",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".md": "markdown",
    ".rst": "restructuredtext",
}

DOCS_LANGUAGES = {"markdown", "restructuredtext"}
CONFIG_LANGUAGES = {"toml", "ini", "yaml", "json"}


def _is_test_path(path: Path) -> bool:
    if "tests" in path.parts[:-1] or "test" in path.parts[:-1]:
        return True
    stem = path.stem
    return stem.startswith("test_") or stem.endswith("_test")


def classify_file(path: Path) -> dict:
    path = Path(path)
    language = LANGUAGE_BY_EXTENSION.get(path.suffix)

    if language == "python" and _is_test_path(path):
        file_kind = "test"
    elif language in CONFIG_LANGUAGES:
        file_kind = "config"
    elif language in DOCS_LANGUAGES:
        file_kind = "docs"
    else:
        file_kind = "source"

    return {"language": language, "file_kind": file_kind}


def discover_files(project_root: Path, config: ProjectConfig) -> list[dict]:
    project_root = Path(project_root)
    records = []

    for path in sorted(project_root.rglob("*")):
        if not path.is_file():
            continue

        relative_path = path.relative_to(project_root)
        if relative_path.parts[0] in ALWAYS_EXCLUDED_DIRS:
            continue
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

    return records
