"""Django as a framework plugin: symbol roles (models, views, migrations,
...) and the views tests reach through `reverse("ns:name")`.
"""

import json
import posixpath
import sqlite3
from pathlib import Path

from project_mcp.plugins.django.metadata import enrich_django_metadata
from project_mcp.plugins.django.urls import (
    extract_url_patterns,
    extract_url_reverses,
)
from project_mcp.plugins.python.linking import (
    _analyze_python_file,
    _imported_modules,
    _imported_names,
    _link_test_symbol,
    _read_source,
    resolve_source_root_imports,
)


def _django_views_by_url_name(
    project_root: Path, path_to_file_id: dict, source_roots: list[str]
) -> dict[str, str]:
    """Map each `namespace:name` URL in the project's urls.py files to its view.

    A urls module's namespaces come from the `include()`s reaching it (their
    `namespace=` and the included app name, nested includes joined with `:`);
    a module nothing includes is namespaced by its own `app_name`.
    """
    url_modules = {}
    for path in sorted(path_to_file_id):
        if posixpath.basename(path) != "urls.py":
            continue
        source = _read_source(Path(project_root) / path)
        if source is None:
            continue
        try:
            url_modules[path] = (source, extract_url_patterns(source))
        except SyntaxError:
            continue

    includers: dict[str, list[tuple[str, set]]] = {}
    for path, (_, urls) in url_modules.items():
        for included in urls["includes"]:
            (resolved,) = resolve_source_root_imports(
                [{"module": included["module"], "level": 0}],
                source_roots,
                path_to_file_id,
            )
            child = resolved["module"].replace(".", "/") + ".py"
            if child not in url_modules:
                continue
            app_name = included["app_name"] or url_modules[child][1]["app_name"]
            segments = {included["namespace"], app_name} - {None}
            includers.setdefault(child, []).append((path, segments))

    def prefixes(path: str, visiting: frozenset) -> set[str]:
        parents = [p for p in includers.get(path, []) if p[0] not in visiting]
        if not parents:
            return {url_modules[path][1]["app_name"] or ""}
        found = set()
        for parent, segments in parents:
            for prefix in prefixes(parent, visiting | {path}):
                found.update(
                    ":".join(part for part in (prefix, segment) if part)
                    for segment in segments or {""}
                )
        return found

    views = {}
    for path, (source, urls) in url_modules.items():
        imports = resolve_source_root_imports(
            _analyze_python_file(path, source)["imports"], source_roots, path_to_file_id
        )
        imported_names = _imported_names(imports)
        imported_modules = _imported_modules(imports)
        module = path[: -len(".py")].replace("/", ".")
        namespaces = sorted(prefixes(path, frozenset()))
        for pattern in urls["patterns"]:
            head, _, rest = pattern["view"].partition(".")
            if head in imported_names:
                base = ".".join(imported_names[head])
            else:
                base = imported_modules.get(head, f"{module}.{head}")
            for namespace in namespaces:
                url_name = f"{namespace}:{pattern['name']}" if namespace else pattern["name"]
                views.setdefault(url_name, f"{base}.{rest}" if rest else base)
    return views


def index_django_url_relationships(
    conn: sqlite3.Connection,
    project_id: int,
    project_root: Path,
    path_to_file_id: dict,
    source_roots: list[str],
) -> None:
    """Link tests to the views their `reverse("ns:name")` calls route to."""
    conn.execute(
        """
        DELETE FROM relationships
        WHERE evidence_json = '["url_reverse"]' AND source_entity_type = 'symbol'
          AND source_entity_id IN (
            SELECT s.id FROM symbols s JOIN files f ON f.id = s.file_id
            WHERE f.project_id = ?
          )
        """,
        (project_id,),
    )
    views = _django_views_by_url_name(project_root, path_to_file_id, source_roots)
    if not views:
        return
    test_files = conn.execute(
        """
        SELECT id, path FROM files
        WHERE project_id = ? AND file_kind = 'test' AND language = 'python'
        """,
        (project_id,),
    ).fetchall()
    for file_id, path in test_files:
        source = _read_source(Path(project_root) / path)
        if source is None or "reverse" not in source:
            continue
        try:
            reverses = extract_url_reverses(path, source)
        except SyntaxError:
            continue
        for reverse in reverses:
            view = views.get(reverse["url_name"])
            if view is not None:
                _link_test_symbol(
                    conn, project_id, file_id, reverse["caller"], view,
                    "references", "url_reverse",
                )


def enrich_django_symbols(conn: sqlite3.Connection, project_id: int) -> None:
    """Enrich symbols with framework-specific metadata (Django, etc.)."""
    # Only enrich if there are symbols to process
    symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    if symbol_count == 0:
        return

    # Get symbols and files for enrichment
    # Fetch both in minimal queries to avoid redundant database access
    symbols = conn.execute(
        """SELECT s.name, s.qualified_name, s.kind, s.metadata_json FROM symbols s
           INNER JOIN files f ON s.file_id = f.id
           WHERE f.project_id = ?""",
        (project_id,),
    ).fetchall()

    files = conn.execute(
        "SELECT path FROM files WHERE project_id = ?", (project_id,)
    ).fetchall()

    # Convert DB rows to format expected by detectors
    symbol_dicts = []
    for name, qname, kind, metadata_json in symbols:
        try:
            metadata = json.loads(metadata_json) if metadata_json else {}
        except json.JSONDecodeError:
            # Skip symbols with malformed metadata
            metadata = {}
        symbol_dict = {
            "name": name,
            "qualified_name": qname,
            "kind": kind,
            "bases": metadata.get("bases", []),
        }
        symbol_dicts.append(symbol_dict)

    file_dicts = [{"path": f[0]} for f in files]

    # Call Django enrichment
    enriched = enrich_django_metadata(symbol_dicts, file_dicts, [])

    # Update symbols with framework metadata
    for enrichment in enriched:
        if "qualified_name" in enrichment:
            # Merge framework_kind into existing metadata
            # Use JOIN to ensure we only update symbols in this project
            conn.execute(
                """UPDATE symbols SET metadata_json = json_set(
                    COALESCE(metadata_json, '{}'),
                    '$.framework_kind',
                    ?
                ) WHERE qualified_name = ?
                AND file_id IN (SELECT id FROM files WHERE project_id = ?)""",
                (enrichment.get("framework_kind"), enrichment["qualified_name"], project_id),
            )
        elif "path" in enrichment:
            # A file-level kind applies to its symbols unless they have their own.
            conn.execute(
                """UPDATE symbols SET metadata_json = json_set(
                    COALESCE(metadata_json, '{}'),
                    '$.framework_kind',
                    ?
                ) WHERE json_extract(COALESCE(metadata_json, '{}'), '$.framework_kind') IS NULL
                AND file_id IN (
                    SELECT id FROM files WHERE project_id = ? AND path = ?
                )""",
                (enrichment.get("framework_kind"), project_id, enrichment["path"]),
            )


class DjangoFramework:
    def detect(self, context) -> bool:
        """Django patterns are recognised per symbol, so any Python project qualifies."""
        return any(path.endswith(".py") for path in context.path_to_file_id)

    def enrich(self, context) -> None:
        if "python" in context.changed_languages:
            index_django_url_relationships(
                context.conn,
                context.project_id,
                context.project_root,
                context.path_to_file_id,
                context.source_roots,
            )
        enrich_django_symbols(context.conn, context.project_id)
