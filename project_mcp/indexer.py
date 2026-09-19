import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from project_mcp.analyzers.frameworks.django import enrich_django_metadata
from project_mcp.analyzers.generic.architecture import (
    detect_architecture_doc_sources,
    extract_architecture_facts,
)
from project_mcp.analyzers.generic.filesystem import discover_files
from project_mcp.analyzers.generic.git import (
    get_file_change_count,
    get_file_last_changed,
)
from project_mcp.analyzers.python.parser import (
    extract_imports,
    extract_static_calls,
    parse_python_source,
)
from project_mcp.analyzers.python.pytest_analyzer import (
    build_test_relationships,
    discover_tests,
)
from project_mcp.config import ProjectConfig
from project_mcp.tools.dependencies import list_dependencies
from project_mcp.schema import get_schema_version


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
    conn.commit()
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
    conn.commit()
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
    conn.commit()


def index_python_symbols(
    conn: sqlite3.Connection, file_id: int, path: str, source: str
) -> list[dict]:
    symbols = parse_python_source(path, source)
    conn.execute(
        """
        DELETE FROM relationships
        WHERE (source_entity_type = 'symbol' AND source_entity_id IN
               (SELECT id FROM symbols WHERE file_id = ?))
           OR (target_entity_type = 'symbol' AND target_entity_id IN
               (SELECT id FROM symbols WHERE file_id = ?))
        """,
        (file_id, file_id),
    )
    conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))

    if len(symbols) == 1 and symbols[0].get("kind") == "parse_error":
        conn.commit()
        return symbols

    for symbol in symbols:
        metadata = (
            json.dumps({"bases": symbol["bases"]}) if symbol["kind"] == "class" else None
        )
        conn.execute(
            """
            INSERT INTO symbols (
                file_id, name, qualified_name, kind, language,
                start_line, end_line, visibility, metadata_json
            ) VALUES (?, ?, ?, ?, 'python', ?, ?, ?, ?)
            """,
            (
                file_id,
                symbol["name"],
                symbol["qualified_name"],
                symbol["kind"],
                symbol["start_line"],
                symbol["end_line"],
                symbol["visibility"],
                metadata,
            ),
        )
    conn.commit()
    return symbols


def index_python_inheritance_relationships(
    conn: sqlite3.Connection, file_id: int, module_name: str, classes: list[dict]
) -> None:
    conn.execute(
        """
        DELETE FROM relationships
        WHERE source_entity_type = 'symbol' AND relationship_type = 'inherits'
          AND source_entity_id IN (SELECT id FROM symbols WHERE file_id = ?)
        """,
        (file_id,),
    )

    for class_symbol in classes:
        class_row = conn.execute(
            "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?",
            (file_id, class_symbol["qualified_name"]),
        ).fetchone()
        if class_row is None:
            continue
        class_symbol_id = class_row[0]

        for base in class_symbol["bases"]:
            if not isinstance(base, str) or "." in base:
                continue
            base_row = conn.execute(
                "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?",
                (file_id, f"{module_name}.{base}"),
            ).fetchone()
            if base_row is None:
                continue
            conn.execute(
                """
                INSERT INTO relationships (
                    source_entity_type, source_entity_id,
                    target_entity_type, target_entity_id,
                    relationship_type, confidence
                ) VALUES ('symbol', ?, 'symbol', ?, 'inherits', 'high')
                """,
                (class_symbol_id, base_row[0]),
            )
    conn.commit()


def index_python_call_relationships(
    conn: sqlite3.Connection, file_id: int, calls: list[dict]
) -> None:
    module_row = conn.execute(
        "SELECT qualified_name FROM symbols WHERE file_id = ? AND kind = 'module'",
        (file_id,),
    ).fetchone()
    if module_row is None:
        return
    module_name = module_row[0]

    for call in calls:
        caller_row = conn.execute(
            "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?",
            (file_id, call["caller"]),
        ).fetchone()
        if caller_row is None:
            continue
        callee_row = conn.execute(
            "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?",
            (file_id, f"{module_name}.{call['callee']}"),
        ).fetchone()
        if callee_row is None:
            continue
        conn.execute(
            """
            INSERT INTO relationships (
                source_entity_type, source_entity_id,
                target_entity_type, target_entity_id,
                relationship_type, confidence
            ) VALUES ('symbol', ?, 'symbol', ?, 'calls', 'high')
            """,
            (caller_row[0], callee_row[0]),
        )
    conn.commit()


def index_python_import_relationships(
    conn: sqlite3.Connection,
    file_id: int,
    imports: list[dict],
    path_to_file_id: dict,
) -> None:
    conn.execute(
        """
        DELETE FROM relationships
        WHERE source_entity_type = 'file' AND source_entity_id = ?
          AND relationship_type = 'imports'
        """,
        (file_id,),
    )

    for imp in imports:
        if imp.get("dynamic") or imp["level"] != 0 or not imp["module"]:
            continue
        module_path = imp["module"].replace(".", "/")
        candidate_paths = [module_path + ".py"]
        candidate_paths.extend(
            f"{module_path}/{name}.py" for name in imp.get("names", [])
        )
        target_file_id = next(
            (path_to_file_id.get(path) for path in candidate_paths
             if path_to_file_id.get(path) is not None),
            None,
        )
        if target_file_id is None:
            continue
        conn.execute(
            """
            INSERT INTO relationships (
                source_entity_type, source_entity_id,
                target_entity_type, target_entity_id,
                relationship_type, confidence
            ) VALUES ('file', ?, 'file', ?, 'imports', 'high')
            """,
            (file_id, target_file_id),
        )
    conn.commit()


def index_python_test_relationships(
    conn: sqlite3.Connection,
    file_id: int,
    path: str,
    source: str,
    path_to_file_id: dict,
) -> None:
    conn.execute(
        """
        DELETE FROM relationships
        WHERE source_entity_type = 'file' AND source_entity_id = ?
          AND relationship_type = 'tests'
        """,
        (file_id,),
    )

    for relationship in build_test_relationships(path, source):
        module_path = relationship["target_module"].replace(".", "/")
        target_file_id = path_to_file_id.get(module_path + ".py")
        if target_file_id is None:
            continue
        conn.execute(
            """
            INSERT INTO relationships (
                source_entity_type, source_entity_id,
                target_entity_type, target_entity_id,
                relationship_type, confidence, evidence_json
            ) VALUES ('file', ?, 'file', ?, 'tests', ?, ?)
            """,
            (
                file_id,
                target_file_id,
                relationship["confidence"],
                json.dumps(relationship["evidence"]),
            ),
        )
    conn.commit()


def index_python_tests(
    conn: sqlite3.Connection, file_id: int, path: str, source: str
) -> None:
    """Index pytest tests found in a Python file."""
    tests = discover_tests(path, source)
    for test in tests:
        conn.execute(
            """
            INSERT INTO tests (file_id, test_kind, framework)
            VALUES (?, ?, ?)
            """,
            (file_id, test["kind"], "pytest"),
        )
    conn.commit()


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


def index_python_dependencies(
    conn: sqlite3.Connection, project_id: int, project_root: Path
) -> None:
    conn.execute(
        "DELETE FROM dependencies WHERE project_id = ? AND ecosystem = 'python'",
        (project_id,),
    )
    for dependency in list_dependencies(project_root, ecosystem="python"):
        status = dependency["version_status"]
        conn.execute(
            """
            INSERT INTO dependencies (
                project_id, name, ecosystem, declared_version, resolved_version
            ) VALUES (?, ?, 'python', ?, ?)
            """,
            (
                project_id,
                dependency["name"],
                dependency["version"] if status == "declared" else None,
                dependency["version"] if status == "resolved" else None,
            ),
        )
    conn.commit()


def index_git_facts(
    conn: sqlite3.Connection,
    project_root: Path,
    path_to_file_id: dict,
    config: ProjectConfig | None = None,
) -> None:
    """Persist per-file git change history for all indexed files."""
    for path, file_id in path_to_file_id.items():
        change_count = get_file_change_count(project_root, path, config=config)
        last_changed = get_file_last_changed(project_root, path)
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
    conn.commit()


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
    conn.commit()


def run_scan(
    conn: sqlite3.Connection, project_root: Path, config: ProjectConfig
) -> int:
    project_id = begin_index(conn, project_root)

    existing_rows = {
        row[0]: (row[1], row[2], row[3])
        for row in conn.execute(
            "SELECT path, id, size, mtime_ns FROM files WHERE project_id = ?",
            (project_id,),
        ).fetchall()
    }
    path_to_file_id = {path: values[0] for path, values in existing_rows.items()}

    discovered = discover_files(project_root, config)
    discovered_paths = set()
    changed_python_files = {}
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

        if record["language"] == "python":
            source = (Path(project_root) / record["path"]).read_text()
            symbols = index_python_symbols(conn, file_id, record["path"], source)
            calls = extract_static_calls(record["path"], source)
            try:
                imports = extract_imports(record["path"], source)
            except SyntaxError:
                imports = []
            changed_python_files[record["path"]] = imports

            classes = [s for s in symbols if s.get("kind") == "class"]
            if classes:
                module_symbol = next(s for s in symbols if s["kind"] == "module")
                index_python_inheritance_relationships(
                    conn, file_id, module_symbol["qualified_name"], classes
                )
            index_python_call_relationships(conn, file_id, calls)
            index_python_tests(conn, file_id, record["path"], source)

    existing_paths = set(existing_rows.keys())
    for stale_path in existing_paths - discovered_paths:
        remove_file(conn, project_id, stale_path)
        path_to_file_id.pop(stale_path, None)

    # A newly-added file can resolve another file's previously-unresolvable
    # import, so a brand-new file forces a full refresh of every python
    # file's import relationships. Otherwise, only the files that actually
    # changed this scan need their import relationships recomputed.
    new_file_added = any(path not in existing_rows for path in changed_python_files)
    if new_file_added:
        paths_to_refresh = [
            path for path in path_to_file_id if Path(path).suffix == ".py"
        ]
    else:
        paths_to_refresh = list(changed_python_files)

    for path in paths_to_refresh:
        file_id = path_to_file_id[path]
        source = (Path(project_root) / path).read_text()
        if path in changed_python_files:
            imports = changed_python_files[path]
        else:
            try:
                imports = extract_imports(path, source)
            except SyntaxError:
                imports = []
        index_python_import_relationships(conn, file_id, imports, path_to_file_id)
        index_python_test_relationships(conn, file_id, path, source, path_to_file_id)

    index_python_dependencies(conn, project_id, project_root)
    _enrich_framework_metadata(conn, project_id)
    index_git_facts(conn, project_root, path_to_file_id, config)
    index_architecture_facts(conn, project_root, config)
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
    conn.commit()


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
    conn: sqlite3.Connection, project_root: Path, config: ProjectConfig
) -> None:
    """Incrementally refresh index, only re-analyzing changed files."""
    project_row = conn.execute(
        "SELECT id FROM projects WHERE root_path = ?", (str(project_root),)
    ).fetchone()
    if not project_row:
        run_scan(conn, project_root, config)
        return

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

    discovered = discover_files(project_root, config)
    discovered_paths = set()
    changed_python_files = {}
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

        if record["language"] == "python":
            source = (Path(project_root) / record["path"]).read_text()
            symbols = index_python_symbols(conn, file_id, record["path"], source)
            calls = extract_static_calls(record["path"], source)
            try:
                imports = extract_imports(record["path"], source)
            except SyntaxError:
                imports = []
            changed_python_files[record["path"]] = imports

            classes = [s for s in symbols if s.get("kind") == "class"]
            if classes:
                module_symbol = next(s for s in symbols if s["kind"] == "module")
                index_python_inheritance_relationships(
                    conn, file_id, module_symbol["qualified_name"], classes
                )
            index_python_call_relationships(conn, file_id, calls)
            index_python_tests(conn, file_id, record["path"], source)

    existing_paths = set(existing_rows.keys())
    for stale_path in existing_paths - discovered_paths:
        remove_file(conn, project_id, stale_path)
        path_to_file_id.pop(stale_path, None)

    new_file_added = any(path not in existing_rows for path in changed_python_files)
    if new_file_added:
        paths_to_refresh = [
            path for path in path_to_file_id if Path(path).suffix == ".py"
        ]
    else:
        paths_to_refresh = list(changed_python_files)

    for path in paths_to_refresh:
        file_id = path_to_file_id[path]
        source = (Path(project_root) / path).read_text()
        if path in changed_python_files:
            imports = changed_python_files[path]
        else:
            try:
                imports = extract_imports(path, source)
            except SyntaxError:
                imports = []
        index_python_import_relationships(conn, file_id, imports, path_to_file_id)
        index_python_test_relationships(conn, file_id, path, source, path_to_file_id)

    index_python_dependencies(conn, project_id, project_root)
    _enrich_framework_metadata(conn, project_id)
    index_git_facts(conn, project_root, path_to_file_id, config)
    index_architecture_facts(conn, project_root, config)
    mark_index_complete(conn)


def ensure_fresh_index(
    conn: sqlite3.Connection, project_root: Path, config: ProjectConfig
) -> None:
    """Guarantee the index reflects the current filesystem before a tool reads it.

    Never indexed -> full scan. Stale (files changed/added/removed on disk
    since the last index) -> incremental refresh. Already fresh -> no-op.
    """
    status = get_index_status(conn, project_root, config)["status"]
    if status == "never_indexed":
        run_scan(conn, project_root, config)
    elif status == "stale":
        refresh_index(conn, project_root, config)
