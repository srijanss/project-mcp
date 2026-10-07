"""The `coverage` block: which plugins analyzed the files a query touched."""

import sqlite3

from project_mcp.plugins.registry import PluginRegistry

_PATHS_PER_QUERY = 500
_MAX_PATH_CHARS = 4096


def coverage_block(
    conn: sqlite3.Connection, registry: PluginRegistry, paths: set[str]
) -> dict:
    """Coverage of the indexed files at `paths`, one entry per language.

    No paths means the query touched no particular file, so its scope is
    the whole project.
    """
    plugin_by_language = {
        language: descriptor.name
        for descriptor in registry.language_descriptors()
        for language in descriptor.extensions.values()
    }
    failed_by_language: dict[str, dict[str, str]] = {}
    for path, language, status, error in _files(conn, paths):
        if language in plugin_by_language:
            errors = failed_by_language.setdefault(language, {})
            if status == "file_failed":
                errors[path] = error
    languages = {
        language: _language_entry(registry, language, plugin_by_language[language], errors)
        for language, errors in failed_by_language.items()
    }
    return {
        "status": _status([entry["analyzed"] for entry in languages.values()]),
        "active_plugins": registry.active_plugins(),
        "languages": languages,
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
        }
    if not registry.analyzed(language):
        return {"analyzed": False, "reason": "plugin_disabled"}
    if failed_files:
        return {"analyzed": False, "reason": "file_failed", "errors": failed_files}
    return {"analyzed": True}


def _status(analyzed: list[bool]) -> str:
    if all(analyzed):
        return "full"
    return "partial" if any(analyzed) else "none"
