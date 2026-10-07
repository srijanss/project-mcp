import json
import posixpath
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from project_mcp.analyzers.frameworks.django import enrich_django_metadata
from project_mcp.analyzers.frameworks.django_urls import (
    extract_url_patterns,
    extract_url_reverses,
)
from project_mcp.analyzers.generic.architecture import (
    detect_architecture_doc_sources,
    extract_architecture_facts,
)
from project_mcp.analyzers.generic.filesystem import discover_files
from project_mcp.language_index import (
    link_imports,
    write_file_analysis,
)
from project_mcp.plugins.analysis import ChangedFile, LinkContext
from project_mcp.plugins.python.linking import (
    _analyze_python_file,
    _imported_modules,
    _imported_names,
    _link_test_symbol,
    resolve_source_root_imports,
)
from project_mcp.plugins.registry import PluginRegistry, builtin_registry
from project_mcp.analyzers.generic.git import collect_git_file_stats
from project_mcp.analyzers.generic.legacy import (
    detect_churn_signals,
    detect_circular_dependency_signals,
    detect_fan_signals,
    detect_structural_signals,
    detect_temporal_coupling_signals,
    detect_test_signals,
)
from project_mcp.config import ProjectConfig
from project_mcp.tools.dependencies import list_dependencies
from project_mcp.schema import get_schema_version


def _read_source(path: Path) -> str:
    """Read a source file, replacing bytes that are not valid UTF-8.

    One legacy-encoded file must not abort the whole index, and replacement
    keeps line numbers intact.
    """
    return path.read_text(errors="replace")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def begin_index(conn: sqlite3.Connection, project_root: Path) -> int:
    root_path = str(Path(project_root))

    conn.execute(
        "INSERT OR IGNORE INTO projects (root_path, created_at) VALUES (?, ?)",
        (root_path, _now()),
    )
    row = conn.execute(
        "SELECT id FROM projects WHERE root_path = ?", (root_path,)
    ).fetchone()
    conn.execute(
        """
        INSERT INTO index_metadata (key, value) VALUES ('index_status', 'indexing')
        ON CONFLICT (key) DO UPDATE SET value = excluded.value
        """
    )
    return row[0]


def upsert_file(
    conn: sqlite3.Connection,
    project_id: int,
    path: str,
    *,
    language: str | None = None,
    file_kind: str | None = None,
    size: int | None = None,
    mtime_ns: int | None = None,
    content_hash: str | None = None,
    parser_version: str | None = None,
) -> int:
    conn.execute(
        """
        INSERT INTO files (
            project_id, path, language, file_kind, size, mtime_ns,
            content_hash, parser_version, indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (project_id, path) DO UPDATE SET
            language = excluded.language,
            file_kind = excluded.file_kind,
            size = excluded.size,
            mtime_ns = excluded.mtime_ns,
            content_hash = excluded.content_hash,
            parser_version = excluded.parser_version,
            indexed_at = excluded.indexed_at
        """,
        (
            project_id,
            path,
            language,
            file_kind,
            size,
            mtime_ns,
            content_hash,
            parser_version,
            _now(),
        ),
    )
    row = conn.execute(
        "SELECT id FROM files WHERE project_id = ? AND path = ?",
        (project_id, path),
    ).fetchone()
    return row[0]


def remove_file(conn: sqlite3.Connection, project_id: int, path: str) -> None:
    row = conn.execute(
        "SELECT id FROM files WHERE project_id = ? AND path = ?",
        (project_id, path),
    ).fetchone()
    if row is None:
        return
    file_id = row[0]

    symbol_ids = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM symbols WHERE file_id = ?", (file_id,)
        ).fetchall()
    ]
    stale_entity_ids = [("file", file_id)] + [
        ("symbol", symbol_id) for symbol_id in symbol_ids
    ]
    for entity_type, entity_id in stale_entity_ids:
        conn.execute(
            """
            DELETE FROM relationships
            WHERE (source_entity_type = ? AND source_entity_id = ?)
               OR (target_entity_type = ? AND target_entity_id = ?)
            """,
            (entity_type, entity_id, entity_type, entity_id),
        )

    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))


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
        if "reverse" not in source:
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


def mark_index_complete(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO index_metadata (key, value) VALUES ('index_status', 'fresh')
        ON CONFLICT (key) DO UPDATE SET value = excluded.value
        """
    )
    conn.execute(
        """
        INSERT INTO index_metadata (key, value) VALUES ('last_refresh_time', ?)
        ON CONFLICT (key) DO UPDATE SET value = excluded.value
        """,
        (_now(),),
    )
    conn.commit()


def index_dependencies(
    conn: sqlite3.Connection,
    project_id: int,
    project_root: Path,
    registry: PluginRegistry,
) -> None:
    """Store the dependencies every language plugin reads from its manifests."""
    conn.execute("DELETE FROM dependencies WHERE project_id = ?", (project_id,))
    for dependency in list_dependencies(project_root, registry=registry):
        status = dependency["version_status"]
        conn.execute(
            """
            INSERT INTO dependencies (
                project_id, name, ecosystem, declared_version, resolved_version
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                project_id,
                dependency["name"],
                dependency["ecosystem"],
                dependency["version"] if status == "declared" else None,
                dependency["version"] if status == "resolved" else None,
            ),
        )


def index_git_facts(
    conn: sqlite3.Connection, path_to_file_id: dict, git_stats: dict
) -> None:
    """Persist per-file git change history (from collect_git_file_stats)."""
    for path, file_id in path_to_file_id.items():
        change_count = git_stats[path]["change_count"]
        last_changed = git_stats[path]["last_changed"]
        conn.execute(
            """
            INSERT INTO git_facts (file_id, change_count, last_changed, computed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (file_id) DO UPDATE SET
                change_count = excluded.change_count,
                last_changed = excluded.last_changed,
                computed_at = excluded.computed_at
            """,
            (file_id, change_count, last_changed, _now()),
        )


def index_architecture_facts(
    conn: sqlite3.Connection, project_root: Path, config: ProjectConfig | None = None
) -> None:
    """Persist explicit architecture facts detected from doc sources."""
    sources = detect_architecture_doc_sources(project_root, config)
    facts = extract_architecture_facts(project_root, sources)
    conn.execute("DELETE FROM architecture_facts WHERE origin = 'explicit'")
    conn.executemany(
        """
        INSERT INTO architecture_facts (subject, predicate, object, origin, source)
        VALUES (:subject, :predicate, :object, :origin, :source)
        """,
        facts,
    )


def index_legacy_signals(
    conn: sqlite3.Connection,
    project_id: int,
    project_root: Path,
    path_to_file_id: dict,
    file_kinds: dict,
    config: ProjectConfig,
    git_stats: dict | None = None,
) -> None:
    """Persist evidence-backed legacy signals for all indexed files/symbols.

    path_to_file_id/file_kinds are threaded through from the caller's own
    scan bookkeeping rather than re-queried, to avoid an extra files-table
    scan on every index run. git_stats is the caller's collect_git_file_stats
    result for every path, read here when not given.
    """
    if git_stats is None:
        git_stats = collect_git_file_stats(
            project_root, list(path_to_file_id), config=config
        )
    file_id_to_path = {file_id: path for path, file_id in path_to_file_id.items()}

    files_input = []
    for path in path_to_file_id:
        try:
            line_count = len(_read_source(Path(project_root) / path).splitlines())
        except (OSError, UnicodeDecodeError):
            continue
        files_input.append({"path": path, "line_count": line_count})

    symbol_rows = conn.execute(
        """
        SELECT s.qualified_name, s.start_line, s.end_line
        FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE f.project_id = ? AND s.start_line IS NOT NULL AND s.end_line IS NOT NULL
        """,
        (project_id,),
    ).fetchall()
    symbols_input = [
        {"qualified_name": qname, "start_line": start, "end_line": end}
        for qname, start, end in symbol_rows
    ]

    signals = list(detect_structural_signals(files_input, symbols_input, config))

    import_rows = conn.execute(
        """
        SELECT source_entity_id, target_entity_id
        FROM relationships
        WHERE relationship_type = 'imports'
          AND source_entity_type = 'file' AND target_entity_type = 'file'
        """,
    ).fetchall()

    fan_out_counts: dict[str, int] = {}
    fan_in_counts: dict[str, int] = {}
    edges: list[tuple[str, str]] = []
    for source_id, target_id in import_rows:
        source_path = file_id_to_path.get(source_id)
        target_path = file_id_to_path.get(target_id)
        if source_path is None or target_path is None:
            continue
        fan_out_counts[source_path] = fan_out_counts.get(source_path, 0) + 1
        fan_in_counts[target_path] = fan_in_counts.get(target_path, 0) + 1
        edges.append((source_path, target_path))

    fan_targets = [
        {
            "target": path,
            "fan_in": fan_in_counts.get(path, 0),
            "fan_out": fan_out_counts.get(path, 0),
        }
        for path in file_id_to_path.values()
    ]
    signals.extend(detect_fan_signals(fan_targets, config=config))
    signals.extend(detect_circular_dependency_signals(edges))

    churn_rows = conn.execute(
        """
        SELECT f.path, g.change_count
        FROM git_facts g
        JOIN files f ON f.id = g.file_id
        WHERE f.project_id = ?
        """,
        (project_id,),
    ).fetchall()
    churn_targets = [
        {"target": path, "change_count": change_count or 0}
        for path, change_count in churn_rows
    ]
    signals.extend(detect_churn_signals(churn_targets, config=config))

    coupling_targets = [
        {
            "target": path,
            "coupled_file_count": git_stats[path]["coupled_file_count"],
        }
        for path in file_id_to_path.values()
    ]
    signals.extend(detect_temporal_coupling_signals(coupling_targets, config=config))

    test_rows = conn.execute(
        """
        SELECT target_entity_id, confidence
        FROM relationships
        WHERE relationship_type = 'tests' AND target_entity_type = 'file'
        """,
    ).fetchall()
    confidences_by_target: dict[str, list[str]] = {}
    for target_id, confidence in test_rows:
        path = file_id_to_path.get(target_id)
        if path is None:
            continue
        confidences_by_target.setdefault(path, []).append(confidence)

    test_targets = [
        {
            "target": path,
            "test_count": len(confidences_by_target.get(path, [])),
            "confidences": confidences_by_target.get(path, []),
        }
        for path in path_to_file_id
        if file_kinds.get(path) != "test"
    ]
    signals.extend(detect_test_signals(test_targets))

    conn.execute("DELETE FROM legacy_signals")
    conn.executemany(
        """
        INSERT INTO legacy_signals (target, signal, severity, confidence, evidence)
        VALUES (:target, :signal, :severity, :confidence, :evidence)
        """,
        [{**signal, "evidence": json.dumps(signal["evidence"])} for signal in signals],
    )


def _group_by_analyzer(
    registry: PluginRegistry, changed_plugin_files: dict[str, ChangedFile]
) -> dict[object, dict[str, ChangedFile]]:
    """The changed files of each plugin, keyed by the plugin's analyzer."""
    grouped: dict[object, dict[str, ChangedFile]] = {}
    for path, changed_file in changed_plugin_files.items():
        analyzer = registry.analyzer_for(registry.language_for(Path(path)))
        grouped.setdefault(analyzer, {})[path] = changed_file
    return grouped


def _link_plugin_imports(
    conn: sqlite3.Connection,
    project_root: Path,
    registry: PluginRegistry,
    changed_plugin_files: dict[str, ChangedFile],
    existing_rows: dict,
    path_to_file_id: dict[str, int],
    source_roots: list[str],
) -> None:
    """Link the imports of plugin-analyzed files that changed.

    A newly added file can resolve another file's earlier unresolved
    import, so a new file re-links every file its plugin analyzes, across
    all of that plugin's languages (a .js file may import a .ts module).
    """

    def analyzer_of(path: str):
        return registry.analyzer_for(registry.language_for(Path(path)))

    for analyzer, changed in _group_by_analyzer(registry, changed_plugin_files).items():
        if any(path not in existing_rows for path in changed):
            paths = [path for path in path_to_file_id if analyzer_of(path) is analyzer]
        else:
            paths = list(changed)
        for path in paths:
            if path in changed:
                imports = changed[path].analysis.imports
            else:
                source = _read_source(Path(project_root) / path)
                imports = analyzer.analyze(path, source).imports
            link_imports(conn, path, imports, analyzer, path_to_file_id, source_roots)


def _run_link_hooks(
    conn: sqlite3.Connection,
    project_root: Path,
    registry: PluginRegistry,
    changed_plugin_files: dict[str, ChangedFile],
    existing_rows: dict,
    path_to_file_id: dict[str, int],
    source_roots: list[str],
) -> None:
    """Call each plugin's optional link hooks with its changed files.

    Every plugin's link_cross_file runs before any link_test_evidence, so
    test evidence can rely on the cross-file edges of every plugin.
    """

    def analyzer_of(path: str):
        return registry.analyzer_for(registry.language_for(Path(path)))

    contexts = [
        (
            analyzer,
            LinkContext(
                conn=conn,
                project_root=project_root,
                source_roots=source_roots,
                path_to_file_id=path_to_file_id,
                changed=changed,
                added={path for path in changed if path not in existing_rows},
                plugin_paths=[
                    path for path in path_to_file_id if analyzer_of(path) is analyzer
                ],
            ),
        )
        for analyzer, changed in _group_by_analyzer(registry, changed_plugin_files).items()
    ]
    for hook_name in ("link_cross_file", "link_test_evidence"):
        for analyzer, context in contexts:
            hook = getattr(analyzer, hook_name, None)
            if callable(hook):
                hook(context)


def run_scan(
    conn: sqlite3.Connection,
    project_root: Path,
    config: ProjectConfig,
    registry: PluginRegistry | None = None,
) -> int:
    if registry is None:
        registry = builtin_registry()
    project_id = begin_index(conn, project_root)

    existing_rows = {
        row[0]: (row[1], row[2], row[3])
        for row in conn.execute(
            "SELECT path, id, size, mtime_ns FROM files WHERE project_id = ?",
            (project_id,),
        ).fetchall()
    }
    path_to_file_id = {path: values[0] for path, values in existing_rows.items()}

    discovered = discover_files(project_root, config, registry)
    discovered_paths = set()
    python_changed = False
    changed_plugin_files = {}
    for record in discovered:
        discovered_paths.add(record["path"])
        previous = existing_rows.get(record["path"])
        if previous is not None and previous[1:] == (
            record["size"],
            record["mtime_ns"],
        ):
            continue
        file_id = upsert_file(
            conn,
            project_id,
            record["path"],
            language=record["language"],
            file_kind=record["file_kind"],
            size=record["size"],
            mtime_ns=record["mtime_ns"],
        )
        path_to_file_id[record["path"]] = file_id

        analyzer = registry.analyzer_for(record["language"])
        if analyzer is not None:
            source = _read_source(Path(project_root) / record["path"])
            analysis = analyzer.analyze(record["path"], source)
            write_file_analysis(conn, file_id, record["language"], analysis)
            changed_plugin_files[record["path"]] = ChangedFile(file_id, source, analysis)
            python_changed = python_changed or record["language"] == "python"

    existing_paths = set(existing_rows.keys())
    for stale_path in existing_paths - discovered_paths:
        remove_file(conn, project_id, stale_path)
        path_to_file_id.pop(stale_path, None)

    _link_plugin_imports(
        conn,
        project_root,
        registry,
        changed_plugin_files,
        existing_rows,
        path_to_file_id,
        config.source_roots,
    )
    _run_link_hooks(
        conn,
        project_root,
        registry,
        changed_plugin_files,
        existing_rows,
        path_to_file_id,
        config.source_roots,
    )

    if python_changed:
        index_django_url_relationships(
            conn, project_id, project_root, path_to_file_id, config.source_roots
        )

    index_dependencies(conn, project_id, project_root, registry)
    _enrich_framework_metadata(conn, project_id)
    git_stats = collect_git_file_stats(project_root, list(path_to_file_id), config=config)
    index_git_facts(conn, path_to_file_id, git_stats)
    index_architecture_facts(conn, project_root, config)
    file_kinds = {record["path"]: record["file_kind"] for record in discovered}
    index_legacy_signals(
        conn, project_id, project_root, path_to_file_id, file_kinds, config, git_stats
    )
    mark_index_complete(conn)
    return project_id


def _enrich_framework_metadata(conn: sqlite3.Connection, project_id: int) -> None:
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


def _detect_stale_index(
    conn: sqlite3.Connection, project_root: Path, config: ProjectConfig
) -> bool:
    """Check if any indexed files have changed or been deleted on disk."""
    indexed_files = {
        row[0]: (row[1], row[2])
        for row in conn.execute("SELECT path, size, mtime_ns FROM files").fetchall()
    }

    if not indexed_files:
        return False

    discovered = discover_files(project_root, config)
    discovered_by_path = {record["path"]: record for record in discovered}
    discovered_paths = set(discovered_by_path.keys())

    # Check for deleted files
    if set(indexed_files.keys()) != discovered_paths:
        return True

    # Check for modified files
    for path, (size, mtime_ns) in indexed_files.items():
        if path not in discovered_by_path:
            return True
        record = discovered_by_path[path]
        if (size, mtime_ns) != (record["size"], record["mtime_ns"]):
            return True

    return False


def get_index_status(
    conn: sqlite3.Connection,
    project_root: Path | None = None,
    config: ProjectConfig | None = None,
) -> dict:
    row = conn.execute(
        "SELECT value FROM index_metadata WHERE key = 'index_status'"
    ).fetchone()
    status = row[0] if row else "never_indexed"

    if project_root and config and status in ("fresh", "indexing"):
        if _detect_stale_index(conn, project_root, config):
            status = "stale"

    last_refresh = conn.execute(
        "SELECT value FROM index_metadata WHERE key = 'last_refresh_time'"
    ).fetchone()

    return {
        "status": status,
        "schema_version": get_schema_version(conn),
        "last_refresh_time": last_refresh[0] if last_refresh else None,
    }


def refresh_index(
    conn: sqlite3.Connection,
    project_root: Path,
    config: ProjectConfig,
    registry: PluginRegistry | None = None,
) -> None:
    """Incrementally refresh index, only re-analyzing changed files."""
    project_row = conn.execute(
        "SELECT id FROM projects WHERE root_path = ?", (str(project_root),)
    ).fetchone()
    if not project_row:
        run_scan(conn, project_root, config, registry)
        return

    if registry is None:
        registry = builtin_registry()
    project_id = project_row[0]
    begin_index(conn, project_root)

    existing_rows = {
        row[0]: (row[1], row[2], row[3])
        for row in conn.execute(
            "SELECT path, id, size, mtime_ns FROM files WHERE project_id = ?",
            (project_id,),
        ).fetchall()
    }
    path_to_file_id = {path: values[0] for path, values in existing_rows.items()}

    discovered = discover_files(project_root, config, registry)
    discovered_paths = set()
    python_changed = False
    changed_plugin_files = {}
    changed_paths = set()
    for record in discovered:
        discovered_paths.add(record["path"])
        previous = existing_rows.get(record["path"])
        if previous is not None and previous[1:] == (
            record["size"],
            record["mtime_ns"],
        ):
            continue
        changed_paths.add(record["path"])
        file_id = upsert_file(
            conn,
            project_id,
            record["path"],
            language=record["language"],
            file_kind=record["file_kind"],
            size=record["size"],
            mtime_ns=record["mtime_ns"],
        )
        path_to_file_id[record["path"]] = file_id

        analyzer = registry.analyzer_for(record["language"])
        if analyzer is not None:
            source = _read_source(Path(project_root) / record["path"])
            analysis = analyzer.analyze(record["path"], source)
            write_file_analysis(conn, file_id, record["language"], analysis)
            changed_plugin_files[record["path"]] = ChangedFile(file_id, source, analysis)
            python_changed = python_changed or record["language"] == "python"

    existing_paths = set(existing_rows.keys())
    for stale_path in existing_paths - discovered_paths:
        remove_file(conn, project_id, stale_path)
        path_to_file_id.pop(stale_path, None)

    _link_plugin_imports(
        conn,
        project_root,
        registry,
        changed_plugin_files,
        existing_rows,
        path_to_file_id,
        config.source_roots,
    )
    _run_link_hooks(
        conn,
        project_root,
        registry,
        changed_plugin_files,
        existing_rows,
        path_to_file_id,
        config.source_roots,
    )

    if python_changed:
        index_django_url_relationships(
            conn, project_id, project_root, path_to_file_id, config.source_roots
        )

    index_dependencies(conn, project_id, project_root, registry)
    _enrich_framework_metadata(conn, project_id)
    changed_file_ids = {
        path: path_to_file_id[path]
        for path in changed_paths
        if path in path_to_file_id
    }
    git_stats = collect_git_file_stats(project_root, list(path_to_file_id), config=config)
    index_git_facts(conn, changed_file_ids, git_stats)
    index_architecture_facts(conn, project_root, config)
    file_kinds = {record["path"]: record["file_kind"] for record in discovered}
    index_legacy_signals(
        conn, project_id, project_root, path_to_file_id, file_kinds, config, git_stats
    )
    mark_index_complete(conn)


def ensure_fresh_index(
    conn: sqlite3.Connection,
    project_root: Path,
    config: ProjectConfig,
    registry: PluginRegistry | None = None,
) -> None:
    """Guarantee the index reflects the current filesystem before a tool reads it.

    Never indexed -> full scan. Stale (files changed/added/removed on disk
    since the last index) -> incremental refresh. Already fresh -> no-op.
    """
    status = get_index_status(conn, project_root, config)["status"]
    if status == "never_indexed":
        run_scan(conn, project_root, config, registry)
    elif status == "stale":
        refresh_index(conn, project_root, config, registry)
