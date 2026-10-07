"""The `coverage` block: which plugins analyzed the files a query touched."""

import sqlite3
from pathlib import PurePosixPath

from project_mcp.plugins.registry import PluginRegistry

# Data only: which plugin to suggest for files no installed plugin claims.
PLUGIN_FOR_EXTENSION = {
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".php": "php",
    ".rb": "ruby",
    ".scala": "scala",
    ".swift": "swift",
}

_PATHS_PER_QUERY = 500
_MAX_PATH_CHARS = 4096
_FILE_LEVEL_ONLY = (
    "Symbols and relationships are unavailable for these files; results are"
    " file-level only."
)


def coverage_block(
    conn: sqlite3.Connection, registry: PluginRegistry, paths: set[str]
) -> dict:
    """Coverage of the indexed files at `paths`, one entry per language.

    No paths means the query touched no particular file, so its scope is
    the whole project.
    """
    plugin_by_language = _plugin_by_language(registry)
    failed_by_language: dict[str, dict[str, str]] = {}
    not_installed: set[str] = set()
    for path, language, status, error in _files(conn, paths):
        if language in plugin_by_language:
            errors = failed_by_language.setdefault(language, {})
            if status == "file_failed":
                errors[path] = error
        elif language is None and _suggested_plugin(path):
            not_installed.add(_suggested_plugin(path))
    languages = {
        language: _language_entry(registry, language, plugin_by_language[language], errors)
        for language, errors in failed_by_language.items()
    }
    for plugin in sorted(not_installed):
        languages[plugin] = _not_installed_entry(plugin)
    return {
        "status": _status([entry["analyzed"] for entry in languages.values()]),
        "active_plugins": registry.active_plugins(),
        "languages": languages,
    }


def uncovered_languages(conn: sqlite3.Connection, registry: PluginRegistry) -> dict:
    """File counts of the project's languages no active plugin covers: those
    whose plugin is disabled or failed, or that no installed plugin claims."""
    plugin_by_language = _plugin_by_language(registry)
    counts: dict[str, int] = {}
    for path, language, _, _ in _files(conn, set()):
        if language in plugin_by_language:
            plugin = plugin_by_language[language]
            if plugin in registry.failed_plugins or not registry.analyzed(language):
                counts[language] = counts.get(language, 0) + 1
        elif language is None and (plugin := _suggested_plugin(path)):
            counts[plugin] = counts.get(plugin, 0) + 1
    return dict(sorted(counts.items()))


def _suggested_plugin(path: str) -> str | None:
    """The plugin to suggest for an unlabelled file, from its extension."""
    return PLUGIN_FOR_EXTENSION.get(PurePosixPath(path).suffix)


def _plugin_by_language(registry: PluginRegistry) -> dict[str, str]:
    return {
        language: descriptor.name
        for descriptor in registry.language_descriptors()
        for language in descriptor.extensions.values()
    }


def referenced_paths(conn: sqlite3.Connection, value) -> set[str]:
    """The indexed file paths among the strings anywhere in `value`."""
    strings = set(_strings(value))
    return {path for (path,) in _rows_at(conn, "SELECT path FROM files", strings)}


def _strings(value):
    if isinstance(value, str):
        if "\n" not in value and len(value) <= _MAX_PATH_CHARS:
            yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _strings(item)


def _files(conn: sqlite3.Connection, paths: set[str]) -> list[tuple]:
    """(path, language, analysis_status, analysis_error) of the files at `paths`,
    or of every file when `paths` is empty, ordered by language and path."""
    columns = "SELECT path, language, analysis_status, analysis_error FROM files"
    rows = _rows_at(conn, columns, paths) if paths else conn.execute(columns).fetchall()
    return sorted(rows, key=lambda row: (str(row[1]), row[0]))


def _rows_at(conn: sqlite3.Connection, select: str, paths: set[str]) -> list[tuple]:
    """Rows of `select` FROM files limited to `paths`, a chunk of paths per query."""
    ordered = sorted(paths)
    rows = []
    for start in range(0, len(ordered), _PATHS_PER_QUERY):
        chunk = ordered[start : start + _PATHS_PER_QUERY]
        rows += conn.execute(
            f"{select} WHERE path IN ({','.join('?' * len(chunk))})", chunk
        ).fetchall()
    return rows


def _language_entry(
    registry: PluginRegistry, language: str, plugin: str, failed_files: dict[str, str]
) -> dict:
    if plugin in registry.failed_plugins:
        return {
            "analyzed": False,
            "reason": "plugin_failed",
            "error": registry.failed_plugins[plugin],
            "note": f"The {plugin} plugin failed to load (see `error`). {_FILE_LEVEL_ONLY}",
        }
    if not registry.analyzed(language):
        return {
            "analyzed": False,
            "reason": "plugin_disabled",
            "note": (
                f"The {plugin} plugin is installed but disabled. {_FILE_LEVEL_ONLY}"
                " Enable it in mcpctl.toml [plugins]: add it to `enabled`, or remove"
                " it from `disabled`."
            ),
        }
    if failed_files:
        count = len(failed_files)
        return {
            "analyzed": False,
            "reason": "file_failed",
            "errors": failed_files,
            "note": (
                f"The {plugin} plugin could not analyze {count}"
                f" file{'' if count == 1 else 's'} (see `errors`); those files are"
                " file-level only."
            ),
        }
    return {"analyzed": True}


def _not_installed_entry(plugin: str) -> dict:
    return {
        "analyzed": False,
        "reason": "plugin_not_installed",
        "note": (
            f"No {plugin} plugin is installed. {_FILE_LEVEL_ONLY} To analyze them,"
            f" install a project-mcp plugin for {plugin} (an entry point in the"
            " project_mcp.plugins group) and enable it in mcpctl.toml [plugins]."
        ),
    }


def _status(analyzed: list[bool]) -> str:
    if all(analyzed):
        return "full"
    return "partial" if any(analyzed) else "none"
