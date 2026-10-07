import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from project_mcp.analyzers.generic.architecture import (
    detect_architecture_doc_sources,
    extract_architecture_facts,
)
from project_mcp.analyzers.generic.filesystem import discover_files
from project_mcp.language_index import (
    link_imports,
    write_file_analysis,
)
from project_mcp.plugins.analysis import ChangedFile, FrameworkContext, LinkContext
from project_mcp.plugins.registry import PluginRegistry, configured_registry
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


logger = logging.getLogger(__name__)


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


def record_scan_warnings(
    conn: sqlite3.Connection, registry: PluginRegistry, file_count: int
) -> None:
    """Store (and log) why a scan's results are partial; clear stale warnings."""
    warnings = []
    if not any(
        registry.analyzed(language)
        for descriptor in registry.language_descriptors()
        for language in descriptor.extensions.values()
    ):
        warnings.append(
            f"no language plugins active; indexed {file_count} files at file level only"
        )
    for framework, missing in registry.skipped_frameworks().items():
        warnings.append(
            f"{framework} plugin skipped: it requires the {', '.join(missing)} plugin,"
            " which is not active"
        )
    for warning in warnings:
        logger.warning(warning)
    conn.execute(
        """
        INSERT INTO index_metadata (key, value) VALUES ('warnings', ?)
        ON CONFLICT (key) DO UPDATE SET value = excluded.value
        """,
        (json.dumps(warnings),),
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


def _run_frameworks(registry: PluginRegistry, context: FrameworkContext) -> None:
    """Let each framework plugin enrich the index of a project it detects."""
    for framework in registry.frameworks():
        if framework.detect(context):
            framework.enrich(context)


def run_scan(
    conn: sqlite3.Connection,
    project_root: Path,
    config: ProjectConfig,
    registry: PluginRegistry | None = None,
) -> int:
    if registry is None:
        registry = configured_registry(config)
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
    changed_languages = set()
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
            changed_languages.add(record["language"])

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


    index_dependencies(conn, project_id, project_root, registry)
    _run_frameworks(
        registry,
        FrameworkContext(
            conn=conn,
            project_id=project_id,
            project_root=project_root,
            source_roots=config.source_roots,
            path_to_file_id=path_to_file_id,
            changed_languages=changed_languages,
        ),
    )
    git_stats = collect_git_file_stats(project_root, list(path_to_file_id), config=config)
    index_git_facts(conn, path_to_file_id, git_stats)
    index_architecture_facts(conn, project_root, config)
    file_kinds = {record["path"]: record["file_kind"] for record in discovered}
    index_legacy_signals(
        conn, project_id, project_root, path_to_file_id, file_kinds, config, git_stats
    )
    record_scan_warnings(conn, registry, len(path_to_file_id))
    mark_index_complete(conn)
    return project_id


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

    result = {
        "status": status,
        "schema_version": get_schema_version(conn),
        "last_refresh_time": last_refresh[0] if last_refresh else None,
    }
    warnings = conn.execute(
        "SELECT value FROM index_metadata WHERE key = 'warnings'"
    ).fetchone()
    if warnings and json.loads(warnings[0]):
        result["warnings"] = json.loads(warnings[0])
    return result


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
        registry = configured_registry(config)
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
    changed_languages = set()
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
            changed_languages.add(record["language"])

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


    index_dependencies(conn, project_id, project_root, registry)
    _run_frameworks(
        registry,
        FrameworkContext(
            conn=conn,
            project_id=project_id,
            project_root=project_root,
            source_roots=config.source_roots,
            path_to_file_id=path_to_file_id,
            changed_languages=changed_languages,
        ),
    )
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
    record_scan_warnings(conn, registry, len(path_to_file_id))
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
