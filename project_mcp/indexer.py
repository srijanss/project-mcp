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
from project_mcp.plugins.registry import PluginRegistry
from project_mcp.analyzers.generic.git import collect_git_file_stats
from project_mcp.analyzers.generic.legacy import (
    detect_churn_signals,
    detect_circular_dependency_signals,
    detect_fan_signals,
    detect_structural_signals,
    detect_temporal_coupling_signals,
    detect_test_signals,
)
from project_mcp.analyzers.javascript.parser import extract_js_imports, parse_js_source
from project_mcp.analyzers.rust.parser import (
    extract_rust_impls,
    extract_rust_use,
    parse_rust_source,
)
from project_mcp.analyzers.python.parser import (
    analyze_python_source,
    parse_python_source,
)
from project_mcp.analyzers.python.mock_patches import (
    extract_fixture_patches,
    extract_mock_patches,
)
from project_mcp.analyzers.python.pytest_analyzer import (
    build_test_relationships,
    discover_tests,
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


def _clear_file_symbols(conn: sqlite3.Connection, file_id: int) -> None:
    """Delete a file's symbols and every symbol edge touching them."""
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


def index_python_symbols(
    conn: sqlite3.Connection,
    file_id: int,
    path: str,
    source: str,
    symbols: list[dict] | None = None,
) -> list[dict]:
    if symbols is None:
        symbols = parse_python_source(path, source)
    _clear_file_symbols(conn, file_id)

    if len(symbols) == 1 and symbols[0].get("kind") == "parse_error":
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
    return symbols


def index_js_symbols(
    conn: sqlite3.Connection, file_id: int, path: str, source: str, language: str
) -> list[dict]:
    symbols = parse_js_source(path, source)
    conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))

    for symbol in symbols:
        conn.execute(
            """
            INSERT INTO symbols (
                file_id, name, qualified_name, kind, language,
                start_line, end_line, visibility
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                symbol["name"],
                symbol["qualified_name"],
                symbol["kind"],
                language,
                symbol["start_line"],
                symbol["end_line"],
                symbol["visibility"],
            ),
        )
    return symbols


_JS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx")


def _resolve_js_module_candidates(importer_path: str, module: str) -> list[str]:
    if not module.startswith("."):
        return []
    base = posixpath.normpath(posixpath.join(posixpath.dirname(importer_path), module))
    candidates = [base + ext for ext in _JS_EXTENSIONS]
    candidates.extend(f"{base}/index{ext}" for ext in _JS_EXTENSIONS)
    return candidates


def index_js_import_relationships(
    conn: sqlite3.Connection,
    file_id: int,
    path: str,
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
        if imp.get("dynamic") or not imp.get("module"):
            continue
        target_file_id = next(
            (
                path_to_file_id.get(candidate)
                for candidate in _resolve_js_module_candidates(path, imp["module"])
                if path_to_file_id.get(candidate) is not None
            ),
            None,
        )
        if target_file_id is None or target_file_id == file_id:
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


def index_rust_symbols(
    conn: sqlite3.Connection, file_id: int, path: str, source: str
) -> list[dict]:
    symbols = parse_rust_source(path, source)
    _clear_file_symbols(conn, file_id)

    for symbol in symbols:
        conn.execute(
            """
            INSERT INTO symbols (
                file_id, name, qualified_name, kind, language,
                start_line, end_line, visibility
            ) VALUES (?, ?, ?, ?, 'rust', ?, ?, ?)
            """,
            (
                file_id,
                symbol["name"],
                symbol["qualified_name"],
                symbol["kind"],
                symbol["start_line"],
                symbol["end_line"],
                symbol["visibility"],
            ),
        )
    return symbols


def index_rust_impl_relationships(
    conn: sqlite3.Connection, file_id: int, source: str
) -> None:
    conn.execute(
        """
        DELETE FROM relationships
        WHERE source_entity_type = 'symbol' AND relationship_type = 'implements'
          AND source_entity_id IN (SELECT id FROM symbols WHERE file_id = ?)
        """,
        (file_id,),
    )

    module_row = conn.execute(
        "SELECT qualified_name FROM symbols WHERE file_id = ? AND kind = 'module'",
        (file_id,),
    ).fetchone()
    if module_row is None:
        return
    module_name = module_row[0]

    for impl in extract_rust_impls("", source):
        if impl["trait"] is None:
            continue
        struct_row = conn.execute(
            "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?",
            (file_id, f"{module_name}.{impl['struct']}"),
        ).fetchone()
        if struct_row is None:
            continue
        trait_row = conn.execute(
            "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?",
            (file_id, f"{module_name}.{impl['trait']}"),
        ).fetchone()
        if trait_row is None:
            continue
        conn.execute(
            """
            INSERT INTO relationships (
                source_entity_type, source_entity_id,
                target_entity_type, target_entity_id,
                relationship_type, confidence
            ) VALUES ('symbol', ?, 'symbol', ?, 'implements', 'high')
            """,
            (struct_row[0], trait_row[0]),
        )


def _resolve_rust_use_candidates(importer_path: str, use_path: str) -> list[str]:
    if use_path != "crate" and not use_path.startswith("crate::"):
        return []

    segments = importer_path.split("/")
    if "src" not in segments:
        return []
    src_index = segments.index("src")
    crate_root = "/".join(segments[: src_index + 1])

    module_segments = use_path.split("::")[1:]
    if not module_segments:
        return [f"{crate_root}/lib.rs", f"{crate_root}/main.rs"]

    module_path = "/".join([crate_root, *module_segments])
    return [f"{module_path}.rs", f"{module_path}/mod.rs"]


def index_rust_use_relationships(
    conn: sqlite3.Connection,
    file_id: int,
    path: str,
    uses: list[dict],
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

    for use in uses:
        target_file_id = next(
            (
                path_to_file_id.get(candidate)
                for candidate in _resolve_rust_use_candidates(path, use["path"])
                if path_to_file_id.get(candidate) is not None
            ),
            None,
        )
        if target_file_id is None or target_file_id == file_id:
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


def index_python_call_relationships(
    conn: sqlite3.Connection, file_id: int, calls: list[dict]
) -> None:
    symbol_ids: dict[str, int] = {}
    module_name = None
    for symbol_id, qualified_name, kind in conn.execute(
        "SELECT id, qualified_name, kind FROM symbols WHERE file_id = ? ORDER BY id",
        (file_id,),
    ):
        symbol_ids.setdefault(qualified_name, symbol_id)
        if kind == "module" and module_name is None:
            module_name = qualified_name
    if module_name is None:
        return

    seen = set()
    for call in calls:
        caller_id = symbol_ids.get(call["caller"])
        callee_id = symbol_ids.get(f"{module_name}.{call['callee']}")
        if caller_id is None or callee_id is None:
            continue
        if (caller_id, callee_id) in seen:
            continue
        seen.add((caller_id, callee_id))
        conn.execute(
            """
            INSERT INTO relationships (
                source_entity_type, source_entity_id,
                target_entity_type, target_entity_id,
                relationship_type, confidence
            ) VALUES ('symbol', ?, 'symbol', ?, 'calls', 'high')
            """,
            (caller_id, callee_id),
        )


def _same_file_member_resolver(symbols: list[dict], kind: str):
    """A `(class, name) -> qualified name` lookup for members of one kind.

    A member the class doesn't define is looked up on its base classes in the
    same file, depth-first and left to right.
    """
    module_name = next(
        (s["qualified_name"] for s in symbols if s.get("kind") == "module"), None
    )
    members = {s["qualified_name"] for s in symbols if s.get("kind") == kind}
    class_bases = {
        s["qualified_name"]: [
            f"{module_name}.{base}"
            for base in s["bases"]
            if isinstance(base, str) and "." not in base
        ]
        for s in symbols
        if s.get("kind") == "class"
    }

    def find(class_name: str, name: str, visited: set[str]) -> str | None:
        if class_name in visited or class_name not in class_bases:
            return None
        visited.add(class_name)
        if f"{class_name}.{name}" in members:
            return f"{class_name}.{name}"
        for base in class_bases[class_name]:
            found = find(base, name, visited)
            if found is not None:
                return found
        return None

    return lambda class_name, name: find(class_name, name, set())


def index_python_self_call_relationships(
    conn: sqlite3.Connection, file_id: int, self_calls: list[dict], symbols: list[dict]
) -> None:
    """Link `self.method()` calls to the method on the caller's class.

    A method the class doesn't define is looked up on its base classes in the
    same file, depth-first and left to right.
    """
    symbol_ids: dict[str, int] = {}
    for symbol_id, qualified_name in conn.execute(
        "SELECT id, qualified_name FROM symbols WHERE file_id = ? ORDER BY id",
        (file_id,),
    ):
        symbol_ids.setdefault(qualified_name, symbol_id)
    resolve = _same_file_member_resolver(symbols, "method")

    seen = set()
    for call in self_calls:
        caller_id = symbol_ids.get(call["caller"])
        target = resolve(call["class"], call["method"])
        callee_id = symbol_ids.get(target) if target is not None else None
        if caller_id is None or callee_id is None:
            continue
        if (caller_id, callee_id) in seen:
            continue
        seen.add((caller_id, callee_id))
        conn.execute(
            """
            INSERT INTO relationships (
                source_entity_type, source_entity_id,
                target_entity_type, target_entity_id,
                relationship_type, confidence
            ) VALUES ('symbol', ?, 'symbol', ?, 'calls', 'high')
            """,
            (caller_id, callee_id),
        )


def index_python_attribute_relationships(
    conn: sqlite3.Connection, file_id: int, references: list[dict]
) -> None:
    symbol_ids: dict[str, int] = {}
    for symbol_id, qualified_name in conn.execute(
        "SELECT id, qualified_name FROM symbols WHERE file_id = ? ORDER BY id",
        (file_id,),
    ):
        symbol_ids.setdefault(qualified_name, symbol_id)

    seen = set()
    for reference in references:
        referrer_id = symbol_ids.get(reference["referrer"])
        attribute_id = symbol_ids.get(f"{reference['class']}.{reference['attribute']}")
        if referrer_id is None or attribute_id is None:
            continue
        if (referrer_id, attribute_id) in seen:
            continue
        seen.add((referrer_id, attribute_id))
        conn.execute(
            """
            INSERT INTO relationships (
                source_entity_type, source_entity_id,
                target_entity_type, target_entity_id,
                relationship_type, confidence
            ) VALUES ('symbol', ?, 'symbol', ?, 'references', 'high')
            """,
            (referrer_id, attribute_id),
        )


def index_python_class_attribute_relationships(
    conn: sqlite3.Connection, file_id: int, accesses: list[dict], symbols: list[dict]
) -> None:
    """Link `Cls.<name>` to the field of a class defined in the same file.

    A field the class doesn't declare is looked up on its base classes in the
    same file, depth-first and left to right.
    """
    symbol_ids: dict[str, int] = {}
    for symbol_id, qualified_name in conn.execute(
        "SELECT id, qualified_name FROM symbols WHERE file_id = ? ORDER BY id",
        (file_id,),
    ):
        symbol_ids.setdefault(qualified_name, symbol_id)
    module_name = next(
        (s["qualified_name"] for s in symbols if s.get("kind") == "module"), None
    )
    resolve = _same_file_member_resolver(symbols, "field")

    seen = set()
    for access in accesses:
        if not access["object"]:
            continue
        target = resolve(f"{module_name}.{access['object']}", access["attribute"])
        referrer_id = symbol_ids.get(access["referrer"])
        field_id = symbol_ids.get(target) if target is not None else None
        if referrer_id is None or field_id is None:
            continue
        if (referrer_id, field_id) in seen:
            continue
        seen.add((referrer_id, field_id))
        conn.execute(
            """
            INSERT INTO relationships (
                source_entity_type, source_entity_id,
                target_entity_type, target_entity_id,
                relationship_type, confidence
            ) VALUES ('symbol', ?, 'symbol', ?, 'references', 'high')
            """,
            (referrer_id, field_id),
        )


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

    seen = set()
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
        if target_file_id is None or target_file_id in seen:
            continue
        seen.add(target_file_id)
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


def resolve_relative_imports(path: str, imports: list[dict]) -> list[dict]:
    """Rewrite `from .x import y` imports of the file at `path` as absolute ones.

    Imports that climb above the project root are left relative, so the
    resolvers that only accept level-0 imports skip them.
    """
    package = list(Path(path).parent.parts)
    resolved = []
    for imp in imports:
        level = imp["level"]
        if level == 0 or level > len(package):
            resolved.append(imp)
            continue
        base = package[: len(package) - level + 1]
        if imp["module"]:
            base = base + [imp["module"]]
        resolved.append({**imp, "module": ".".join(base), "level": 0})
    return resolved


def resolve_source_root_imports(
    imports: list[dict], source_roots: list[str], path_to_file_id: dict
) -> list[dict]:
    """Rewrite absolute imports of modules under a source root as their indexed names.

    With `src` as a source root, `shop.billing` is indexed as `src.shop.billing`
    (qualified names follow the file path), so `from shop.billing import X`
    becomes `from src.shop.billing import X`. Modules that already resolve
    from the project root are left alone.
    """

    def resolves(module: str, names: list[str]) -> bool:
        module_path = module.replace(".", "/")
        candidates = [f"{module_path}.py", f"{module_path}/__init__.py"]
        candidates.extend(f"{module_path}/{name}.py" for name in names)
        return any(path in path_to_file_id for path in candidates)

    normalized = (posixpath.normpath(root) for root in source_roots)
    roots = [root.replace("/", ".") for root in normalized if root != "."]
    resolved = []
    for imp in imports:
        module, names = imp["module"], imp.get("names", [])
        if imp["level"] == 0 and module and not resolves(module, names):
            for root in roots:
                if resolves(f"{root}.{module}", names):
                    imp = {**imp, "module": f"{root}.{module}"}
                    break
        resolved.append(imp)
    return resolved


def _analyze_python_file(path: str, source: str) -> dict:
    """Parse a python file once, with its relative imports made absolute."""
    analysis = analyze_python_source(path, source)
    analysis["imports"] = resolve_relative_imports(path, analysis["imports"])
    return analysis


def _imported_names(imports: list[dict]) -> dict[str, tuple[str, str]]:
    """Map each name bound by an absolute `from` import to (module, original name)."""
    imported: dict[str, tuple[str, str]] = {}
    for imp in imports:
        if imp.get("dynamic") or imp["level"] != 0 or not imp["module"]:
            continue
        if not imp.get("names"):
            continue  # plain `import x`: binds a module, not a name in it
        aliased = set(imp.get("aliases", {}).values())
        for name in imp["names"]:
            if name not in aliased:
                imported[name] = (imp["module"], name)
        for local_name, name in imp.get("aliases", {}).items():
            imported[local_name] = (imp["module"], name)
    return imported


def _imported_modules(imports: list[dict]) -> dict[str, str]:
    """Map each local name that may refer to a module to that module's dotted name.

    `from pkg import mod` names are candidates only; they resolve when a
    matching `pkg/mod.py` file exists.
    """
    modules: dict[str, str] = {}
    for imp in imports:
        if imp.get("dynamic") or imp["level"] != 0 or not imp["module"]:
            continue
        if not imp.get("names"):
            aliases = imp.get("aliases")
            if aliases:
                modules.update(aliases)
            else:
                modules[imp["module"]] = imp["module"]
    for local_name, (module, name) in _imported_names(imports).items():
        modules.setdefault(local_name, f"{module}.{name}")
    return modules


def _resolve_method_in_class_tree(
    conn: sqlite3.Connection, class_id: int, method: str, visited: set[int]
) -> int | None:
    """Find `method` on a class or, depth-first, on its indexed base classes."""
    if class_id in visited:
        return None
    visited.add(class_id)
    method_row = conn.execute(
        """
        SELECT m.id FROM symbols c
        JOIN symbols m ON m.file_id = c.file_id
                      AND m.qualified_name = c.qualified_name || '.' || ?
        WHERE c.id = ? AND m.kind = 'method'
        """,
        (method, class_id),
    ).fetchone()
    if method_row is not None:
        return method_row[0]
    for (base_id,) in conn.execute(
        """
        SELECT target_entity_id FROM relationships
        WHERE relationship_type = 'inherits'
          AND source_entity_type = 'symbol' AND target_entity_type = 'symbol'
          AND source_entity_id = ?
        ORDER BY id
        """,
        (class_id,),
    ).fetchall():
        found = _resolve_method_in_class_tree(conn, base_id, method, visited)
        if found is not None:
            return found
    return None


def _resolve_class_reference(
    conn: sqlite3.Connection,
    file_id: int,
    class_name: str,
    imports: list[dict],
    path_to_file_id: dict,
) -> int | None:
    """The class symbol a `Cls` / `mod.Cls` name refers to from this file."""
    module_row = conn.execute(
        "SELECT qualified_name FROM symbols WHERE file_id = ? AND kind = 'module'",
        (file_id,),
    ).fetchone()
    if module_row is None:
        return None
    if "." not in class_name:
        local_row = conn.execute(
            "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?"
            " AND kind = 'class'",
            (file_id, f"{module_row[0]}.{class_name}"),
        ).fetchone()
        if local_row is not None:
            return local_row[0]
    imported_from = _imported_names(imports)
    imported_modules = _imported_modules(imports)
    if class_name in imported_from:
        module, name = imported_from[class_name]
    elif "." in class_name and class_name.rsplit(".", 1)[0] in imported_modules:
        prefix, name = class_name.rsplit(".", 1)
        module = imported_modules[prefix]
    else:
        return None
    target_file_id = path_to_file_id.get(module.replace(".", "/") + ".py")
    if target_file_id is None:
        return None
    row = conn.execute(
        "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?"
        " AND kind = 'class'",
        (target_file_id, f"{module}.{name}"),
    ).fetchone()
    return row[0] if row is not None else None


def _typed_call_edges(
    conn: sqlite3.Connection,
    file_id: int,
    typed_calls: list[dict],
    imports: list[dict],
    path_to_file_id: dict,
    attribute_calls: list[dict] = (),
) -> list[tuple[int, int]]:
    """(caller id, method id) for `obj.method()` calls on objects of a known class.

    `Cls.method()` calls count too: their object is the class itself.
    """
    calls = [
        *typed_calls,
        *(
            {"caller": c["caller"], "class": c["object"], "method": c["attribute"]}
            for c in attribute_calls
        ),
    ]
    caller_ids: dict[str, int | None] = {}
    class_ids: dict[str, int | None] = {}
    edges = []
    for call in calls:
        caller = call["caller"]
        if caller not in caller_ids:
            caller_row = conn.execute(
                "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?",
                (file_id, caller),
            ).fetchone()
            caller_ids[caller] = caller_row[0] if caller_row else None
        if call["class"] not in class_ids:
            class_ids[call["class"]] = _resolve_class_reference(
                conn, file_id, call["class"], imports, path_to_file_id
            )
        caller_id, class_id = caller_ids[caller], class_ids[call["class"]]
        if caller_id is None or class_id is None:
            continue
        method_id = _resolve_method_in_class_tree(conn, class_id, call["method"], set())
        if method_id is not None:
            edges.append((caller_id, method_id))
    return edges


def index_python_typed_call_relationships(
    conn: sqlite3.Connection,
    file_id: int,
    typed_calls: list[dict],
    imports: list[dict],
    path_to_file_id: dict,
    attribute_calls: list[dict] = (),
) -> None:
    """Link `obj.method()` and `Cls.method()` calls whose method is defined in this file.

    Methods in other files are linked by
    index_python_cross_module_call_relationships.
    """
    local_ids = {
        row[0]
        for row in conn.execute("SELECT id FROM symbols WHERE file_id = ?", (file_id,))
    }
    seen = set()
    for caller_id, callee_id in _typed_call_edges(
        conn, file_id, typed_calls, imports, path_to_file_id, attribute_calls
    ):
        if callee_id not in local_ids or (caller_id, callee_id) in seen:
            continue
        seen.add((caller_id, callee_id))
        conn.execute(
            """
            INSERT INTO relationships (
                source_entity_type, source_entity_id,
                target_entity_type, target_entity_id,
                relationship_type, confidence
            ) VALUES ('symbol', ?, 'symbol', ?, 'calls', 'high')
            """,
            (caller_id, callee_id),
        )


MAX_UNTYPED_CALL_CANDIDATES = 3


def _untyped_call_edges(
    conn: sqlite3.Connection,
    file_id: int,
    attribute_calls: list[dict],
    typed_calls: list[dict],
    imports: list[dict],
    path_to_file_id: dict,
) -> list[tuple[int, int]]:
    """(caller id, method id) guessed from the method name of `obj.method()` alone.

    Nothing says what `obj` is, so the candidates are the methods of that name
    in the files this one imports; a name shared by more than
    MAX_UNTYPED_CALL_CANDIDATES of them is too ambiguous to guess.
    """
    imported_from = _imported_names(imports)
    imported_modules = _imported_modules(imports)
    imported_files = {
        path_to_file_id.get(module.replace(".", "/") + ".py")
        for module in {m for m, _ in imported_from.values()} | set(imported_modules.values())
    } - {None, file_id}
    if not imported_files:
        return []
    marks = ",".join("?" * len(imported_files))
    known_heads = set(imported_from) | set(imported_modules)
    typed = {(c["caller"], c["method"], c["line"]) for c in typed_calls}

    caller_ids: dict[str, int | None] = {}
    is_class: dict[str, bool] = {}
    candidates: dict[str, list[int]] = {}
    edges = []
    for call in attribute_calls:
        obj, name, caller = call["object"], call["attribute"], call["caller"]
        if obj not in is_class:
            is_class[obj] = (
                _resolve_class_reference(conn, file_id, obj, imports, path_to_file_id)
                is not None
            )
        if (
            obj in ("self", "cls")
            or obj.split(".")[0] in known_heads
            or is_class[obj]
            or (caller, name, call["line"]) in typed
        ):
            continue  # a module, a class, or an object whose type is already known
        if name not in candidates:
            candidates[name] = [
                row[0]
                for row in conn.execute(
                    f"SELECT id FROM symbols WHERE kind = 'method' AND name = ?"
                    f" AND file_id IN ({marks})",
                    (name, *imported_files),
                )
            ]
        if not 0 < len(candidates[name]) <= MAX_UNTYPED_CALL_CANDIDATES:
            continue
        if caller not in caller_ids:
            caller_row = conn.execute(
                "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?",
                (file_id, caller),
            ).fetchone()
            caller_ids[caller] = caller_row[0] if caller_row else None
        if caller_ids[caller] is not None:
            edges.extend((caller_ids[caller], method_id) for method_id in candidates[name])
    return edges


def index_python_cross_module_call_relationships(
    conn: sqlite3.Connection,
    file_id: int,
    calls: list[dict],
    imports: list[dict],
    path_to_file_id: dict,
    attribute_calls: list[dict] = (),
    self_calls: list[dict] = (),
    typed_calls: list[dict] = (),
) -> None:
    conn.execute(
        """
        DELETE FROM relationships
        WHERE relationship_type = 'calls'
          AND source_entity_type = 'symbol' AND target_entity_type = 'symbol'
          AND source_entity_id IN (SELECT id FROM symbols WHERE file_id = ?)
          AND target_entity_id NOT IN (SELECT id FROM symbols WHERE file_id = ?)
        """,
        (file_id, file_id),
    )

    imported_from = _imported_names(imports)
    imported_modules = _imported_modules(imports)
    targets = [
        (call["caller"], *imported_from[call["callee"]])
        for call in calls
        if call["callee"] in imported_from
    ]
    targets.extend(
        (call["caller"], imported_modules[call["object"]], call["attribute"])
        for call in attribute_calls
        if call["object"] in imported_modules
    )

    edges = []
    for caller, module, name in targets:
        target_file_id = path_to_file_id.get(module.replace(".", "/") + ".py")
        if target_file_id is None:
            continue
        caller_row = conn.execute(
            "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?",
            (file_id, caller),
        ).fetchone()
        callee_row = conn.execute(
            "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?",
            (target_file_id, f"{module}.{name}"),
        ).fetchone()
        if caller_row is None or callee_row is None:
            continue
        edges.append((caller_row[0], callee_row[0]))

    # `self.method()` resolved to a base class in another file; same-file
    # targets are linked by index_python_self_call_relationships instead.
    file_symbol_ids = {
        qualified_name: symbol_id
        for symbol_id, qualified_name in conn.execute(
            "SELECT id, qualified_name FROM symbols WHERE file_id = ? ORDER BY id DESC",
            (file_id,),
        )
    }
    local_ids = set(file_symbol_ids.values())
    for call in self_calls:
        caller_id = file_symbol_ids.get(call["caller"])
        class_id = file_symbol_ids.get(call["class"])
        if caller_id is None or class_id is None:
            continue
        callee_id = _resolve_method_in_class_tree(conn, class_id, call["method"], set())
        if callee_id is not None and callee_id not in local_ids:
            edges.append((caller_id, callee_id))
    edges.extend(
        (caller_id, callee_id)
        for caller_id, callee_id in _typed_call_edges(
            conn, file_id, typed_calls, imports, path_to_file_id, attribute_calls
        )
        if callee_id not in local_ids
    )

    guessed = _untyped_call_edges(
        conn, file_id, attribute_calls, typed_calls, imports, path_to_file_id
    )
    seen = set()
    for confidence, found in (("high", edges), ("low", guessed)):
        for caller_id, callee_id in found:
            if (caller_id, callee_id) in seen:
                continue
            seen.add((caller_id, callee_id))
            conn.execute(
                """
                INSERT INTO relationships (
                    source_entity_type, source_entity_id,
                    target_entity_type, target_entity_id,
                    relationship_type, confidence
                ) VALUES ('symbol', ?, 'symbol', ?, 'calls', ?)
                """,
                (caller_id, callee_id, confidence),
            )


def index_python_cross_file_attribute_relationships(
    conn: sqlite3.Connection,
    file_id: int,
    accesses: list[dict],
    imports: list[dict],
    path_to_file_id: dict,
) -> None:
    """Link `obj.<name>` accesses to a field defined in a module this file imports.

    `Cls.<name>` on a class this file can resolve links only to that class's own
    field, or to nothing when it has none (e.g. a framework-provided manager);
    the same goes for a CapWords name this file cannot resolve.
    Other objects are untyped, so they match a uniquely named field instead.
    These edges are heuristic and low confidence.
    """
    conn.execute(
        """
        DELETE FROM relationships
        WHERE relationship_type = 'references' AND confidence = 'low'
          AND source_entity_type = 'symbol' AND target_entity_type = 'symbol'
          AND source_entity_id IN (SELECT id FROM symbols WHERE file_id = ?)
          AND target_entity_id NOT IN (SELECT id FROM symbols WHERE file_id = ?)
        """,
        (file_id, file_id),
    )

    imported_file_ids = [
        row[0]
        for row in conn.execute(
            """
            SELECT target_entity_id FROM relationships
            WHERE relationship_type = 'imports'
              AND source_entity_type = 'file' AND target_entity_type = 'file'
              AND source_entity_id = ?
            """,
            (file_id,),
        )
    ]
    if not imported_file_ids:
        return
    placeholders = ",".join("?" * len(imported_file_ids))
    fields_by_name: dict[str, list[int]] = {}
    for field_id, name in conn.execute(
        f"SELECT id, name FROM symbols WHERE kind = 'field' "
        f"AND file_id IN ({placeholders}) ORDER BY id",
        imported_file_ids,
    ):
        fields_by_name.setdefault(name, []).append(field_id)
    # An attribute name defined by several imported fields is ambiguous
    # without type information, so it is left unlinked.
    field_ids = {
        name: ids[0] for name, ids in fields_by_name.items() if len(ids) == 1
    }

    symbol_ids: dict[str, int] = {}
    for symbol_id, qualified_name in conn.execute(
        "SELECT id, qualified_name FROM symbols WHERE file_id = ? ORDER BY id",
        (file_id,),
    ):
        symbol_ids.setdefault(qualified_name, symbol_id)

    class_ids: dict[str, int | None] = {}

    def own_field(owner: str, attribute: str) -> tuple[bool, int | None]:
        """Whether `owner` names a class, and that class's own field if it has one."""
        if owner not in class_ids:
            class_ids[owner] = _resolve_class_reference(
                conn, file_id, owner, imports, path_to_file_id
            )
        if class_ids[owner] is None:
            # A CapWords name is a class even when it is not one of ours
            # (external, or re-exported); guessing a field for it would be wrong.
            return owner.rsplit(".", 1)[-1][:1].isupper(), None
        row = conn.execute(
            """
            SELECT f.id FROM symbols f
            WHERE f.kind = 'field' AND f.file_id != ?
              AND f.qualified_name = (
                  SELECT qualified_name FROM symbols WHERE id = ?
              ) || '.' || ?
            """,
            (file_id, class_ids[owner], attribute),
        ).fetchone()
        return True, row[0] if row else None

    seen = set()
    for access in accesses:
        referrer_id = symbol_ids.get(access["referrer"])
        is_class, field_id = (
            own_field(access["object"], access["attribute"])
            if access["object"]
            else (False, None)
        )
        if not is_class:
            field_id = field_ids.get(access["attribute"])
        if referrer_id is None or field_id is None:
            continue
        if (referrer_id, field_id) in seen:
            continue
        seen.add((referrer_id, field_id))
        conn.execute(
            """
            INSERT INTO relationships (
                source_entity_type, source_entity_id,
                target_entity_type, target_entity_id,
                relationship_type, confidence
            ) VALUES ('symbol', ?, 'symbol', ?, 'references', 'low')
            """,
            (referrer_id, field_id),
        )


def index_python_constant_reference_relationships(
    conn: sqlite3.Connection,
    file_id: int,
    loads: list[dict],
    imports: list[dict],
    path_to_file_id: dict,
) -> None:
    """Link bare-name reads to module constants and classes, local or `from`-imported."""
    conn.execute(
        """
        DELETE FROM relationships
        WHERE relationship_type = 'references'
          AND source_entity_type = 'symbol' AND target_entity_type = 'symbol'
          AND source_entity_id IN (SELECT id FROM symbols WHERE file_id = ?)
          AND target_entity_id IN (
              SELECT id FROM symbols WHERE kind IN ('constant', 'class')
          )
        """,
        (file_id,),
    )

    symbol_ids: dict[str, int] = {}
    target_ids: dict[str, int] = {}
    for symbol_id, name, qualified_name, kind in conn.execute(
        "SELECT id, name, qualified_name, kind FROM symbols WHERE file_id = ? ORDER BY id",
        (file_id,),
    ):
        symbol_ids.setdefault(qualified_name, symbol_id)
        if kind in ("constant", "class"):
            target_ids.setdefault(name, symbol_id)

    for local_name, (module, name) in _imported_names(imports).items():
        target_file_id = path_to_file_id.get(module.replace(".", "/") + ".py")
        if target_file_id is None:
            continue
        row = conn.execute(
            "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ? "
            "AND kind IN ('constant', 'class')",
            (target_file_id, f"{module}.{name}"),
        ).fetchone()
        if row is not None:
            target_ids[local_name] = row[0]

    seen = set()
    for load in loads:
        referrer_id = symbol_ids.get(load["referrer"])
        target_id = target_ids.get(load["name"])
        if referrer_id is None or target_id is None:
            continue
        if (referrer_id, target_id) in seen:
            continue
        seen.add((referrer_id, target_id))
        conn.execute(
            """
            INSERT INTO relationships (
                source_entity_type, source_entity_id,
                target_entity_type, target_entity_id,
                relationship_type, confidence
            ) VALUES ('symbol', ?, 'symbol', ?, 'references', 'high')
            """,
            (referrer_id, target_id),
        )


def index_python_cross_file_inheritance_relationships(
    conn: sqlite3.Connection,
    file_id: int,
    symbols: list[dict],
    imports: list[dict],
    path_to_file_id: dict,
) -> None:
    """Link classes to base classes imported from other project files.

    Bases are resolved from `from x import Base` names and from `mod.Base`
    where `mod` is an imported module.
    """
    conn.execute(
        """
        DELETE FROM relationships
        WHERE relationship_type = 'inherits'
          AND source_entity_type = 'symbol' AND target_entity_type = 'symbol'
          AND source_entity_id IN (SELECT id FROM symbols WHERE file_id = ?)
          AND target_entity_id NOT IN (SELECT id FROM symbols WHERE file_id = ?)
        """,
        (file_id, file_id),
    )

    local_ids = {
        row[0]
        for row in conn.execute("SELECT id FROM symbols WHERE file_id = ?", (file_id,))
    }
    for class_symbol in symbols:
        if class_symbol.get("kind") != "class":
            continue
        class_row = conn.execute(
            "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?",
            (file_id, class_symbol["qualified_name"]),
        ).fetchone()
        if class_row is None:
            continue
        for base in class_symbol["bases"]:
            if not isinstance(base, str):
                continue
            base_id = _resolve_class_reference(
                conn, file_id, base, imports, path_to_file_id
            )
            # Same-file bases are linked by index_python_inheritance_relationships.
            if base_id is None or base_id in local_ids:
                continue
            conn.execute(
                """
                INSERT INTO relationships (
                    source_entity_type, source_entity_id,
                    target_entity_type, target_entity_id,
                    relationship_type, confidence
                ) VALUES ('symbol', ?, 'symbol', ?, 'inherits', 'high')
                """,
                (class_row[0], base_id),
            )


def index_python_symbol_import_relationships(
    conn: sqlite3.Connection,
    file_id: int,
    imports: list[dict],
    path_to_file_id: dict,
) -> None:
    """Link this file to each symbol another file's `from x import name` brings in.

    These are file-to-symbol `imports` edges, next to the file-to-file ones, so a
    symbol's dependents include importers that never call it (a class body's
    `model = Watch`, a re-export).
    """
    conn.execute(
        """
        DELETE FROM relationships
        WHERE source_entity_type = 'file' AND source_entity_id = ?
          AND target_entity_type = 'symbol' AND relationship_type = 'imports'
        """,
        (file_id,),
    )

    seen = set()
    for module, name in _imported_names(imports).values():
        target_file_id = path_to_file_id.get(module.replace(".", "/") + ".py")
        if target_file_id is None or target_file_id == file_id:
            continue
        row = conn.execute(
            "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?",
            (target_file_id, f"{module}.{name}"),
        ).fetchone()
        if row is None or row[0] in seen:
            continue
        seen.add(row[0])
        conn.execute(
            """
            INSERT INTO relationships (
                source_entity_type, source_entity_id,
                target_entity_type, target_entity_id,
                relationship_type, confidence
            ) VALUES ('file', ?, 'symbol', ?, 'imports', 'high')
            """,
            (file_id, row[0]),
        )


def _index_python_cross_file_edges(
    conn: sqlite3.Connection, file_id: int, analysis: dict, path_to_file_id: dict
) -> None:
    """Recompute the edges from this file's symbols into other files.

    Expects cross-file inherits edges to be current (see
    _index_python_cross_file_edges_for_files).
    """
    index_python_cross_module_call_relationships(
        conn,
        file_id,
        analysis["calls"],
        analysis["imports"],
        path_to_file_id,
        analysis["attribute_calls"],
        analysis["self_calls"],
        analysis["typed_calls"],
    )
    index_python_cross_file_attribute_relationships(
        conn,
        file_id,
        analysis["foreign_accesses"],
        analysis["imports"],
        path_to_file_id,
    )
    index_python_constant_reference_relationships(
        conn, file_id, analysis["name_loads"], analysis["imports"], path_to_file_id
    )
    index_python_symbol_import_relationships(
        conn, file_id, analysis["imports"], path_to_file_id
    )


def _index_python_cross_file_edges_for_files(
    conn: sqlite3.Connection, analyses: list[tuple[int, dict]], path_to_file_id: dict
) -> None:
    """Recompute cross-file edges for several files, inheritance first.

    `self.method()` resolution walks inherits edges through other files, so
    every file's bases must be linked before any file's calls are.
    """
    for file_id, analysis in analyses:
        index_python_cross_file_inheritance_relationships(
            conn, file_id, analysis["symbols"], analysis["imports"], path_to_file_id
        )
    for file_id, analysis in analyses:
        _index_python_cross_file_edges(conn, file_id, analysis, path_to_file_id)


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


def _link_test_symbol(
    conn: sqlite3.Connection,
    project_id: int,
    file_id: int,
    caller: str,
    target: str,
    relationship_type: str,
    evidence: str,
) -> bool:
    """Insert a high-confidence edge from a test-file symbol to a project symbol,
    returning whether both were found."""
    caller_row = conn.execute(
        "SELECT id FROM symbols WHERE file_id = ? AND qualified_name = ?",
        (file_id, caller),
    ).fetchone()
    target_row = conn.execute(
        """
        SELECT s.id FROM symbols s JOIN files f ON f.id = s.file_id
        WHERE f.project_id = ? AND s.qualified_name = ?
        """,
        (project_id, target),
    ).fetchone()
    if caller_row is None or target_row is None:
        return False
    conn.execute(
        """
        INSERT INTO relationships (
            source_entity_type, source_entity_id,
            target_entity_type, target_entity_id,
            relationship_type, confidence, evidence_json
        ) VALUES ('symbol', ?, 'symbol', ?, ?, 'high', ?)
        """,
        (caller_row[0], target_row[0], relationship_type, json.dumps([evidence])),
    )
    return True


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


class _PatchTargetResolver:
    """Follow a dotted name as `patch()` sees it to the symbol it names.

    `patch("app.checkout.process_payment")` replaces the name where checkout
    looks it up; when checkout imported it, the symbol is defined elsewhere.
    """

    def __init__(self, project_root: Path, path_to_file_id: dict, source_roots: list[str]):
        self.project_root = Path(project_root)
        self.path_to_file_id = path_to_file_id
        self.source_roots = source_roots
        self._imports: dict[str, list[dict]] = {}

    def module_imports(self, path: str) -> list[dict]:
        if path not in self._imports:
            source = _read_source(self.project_root / path)
            try:
                imports = _analyze_python_file(path, source)["imports"]
            except SyntaxError:
                imports = []
            self._imports[path] = resolve_source_root_imports(
                imports, self.source_roots, self.path_to_file_id
            )
        return self._imports[path]

    def local(self, path: str, dotted: str) -> str:
        """A dotted name written in the module at `path`, as a project-wide name."""
        head, _, rest = dotted.partition(".")
        imports = self.module_imports(path)
        imported_names = _imported_names(imports)
        if head in imported_names:
            base = ".".join(imported_names[head])
        else:
            module = path[: -len(".py")].replace("/", ".")
            base = _imported_modules(imports).get(head, f"{module}.{head}")
        return f"{base}.{rest}" if rest else base

    def resolve(self, dotted: str) -> str:
        parts = dotted.split(".")
        for split in range(len(parts) - 1, 0, -1):
            (imp,) = resolve_source_root_imports(
                [{"module": ".".join(parts[:split]), "level": 0}],
                self.source_roots,
                self.path_to_file_id,
            )
            module_path = imp["module"].replace(".", "/")
            for path in (f"{module_path}.py", f"{module_path}/__init__.py"):
                if path in self.path_to_file_id:
                    return self.local(path, ".".join(parts[split:]))
        return dotted


def index_mock_patch_relationships(
    conn: sqlite3.Connection,
    project_id: int,
    project_root: Path,
    path_to_file_id: dict,
    source_roots: list[str],
) -> None:
    """Link tests to the symbols their `patch(...)` calls replace."""
    conn.execute(
        """
        DELETE FROM relationships
        WHERE relationship_type = 'mocks' AND source_entity_type = 'symbol'
          AND source_entity_id IN (
            SELECT s.id FROM symbols s JOIN files f ON f.id = s.file_id
            WHERE f.project_id = ?
          )
        """,
        (project_id,),
    )
    resolver = _PatchTargetResolver(project_root, path_to_file_id, source_roots)
    conftest_fixtures = _conftest_fixture_patches(project_root, path_to_file_id, resolver)
    test_files = conn.execute(
        """
        SELECT id, path FROM files
        WHERE project_id = ? AND file_kind = 'test' AND language = 'python'
        """,
        (project_id,),
    ).fetchall()
    for file_id, path in test_files:
        # Nearer conftest.py files override fixtures of the same name.
        outer_fixtures = {}
        for directory in reversed(Path(path).parents):
            outer_fixtures.update(conftest_fixtures.get(directory.as_posix(), {}))
        source = _read_source(Path(project_root) / path)
        if "patch" not in source and not outer_fixtures:
            continue
        try:
            patches = extract_mock_patches(path, source, outer_fixtures)
        except SyntaxError:
            continue
        for patch in patches:
            linked = _link_test_symbol(
                conn,
                project_id,
                file_id,
                patch["caller"],
                _patched_symbol(resolver, path, patch),
                "mocks",
                "mock_patch",
            )
            if not linked and "attribute" in patch:
                _link_test_to_methods_named(
                    conn, project_id, file_id, patch["caller"], patch["attribute"]
                )


def _link_test_to_methods_named(
    conn: sqlite3.Connection, project_id: int, file_id: int, caller: str, name: str
) -> None:
    """`patch.object(self.api, "_post")` on an object no import names: link the
    test to every method so named outside the tests, at low confidence."""
    conn.execute(
        """
        INSERT INTO relationships (
            source_entity_type, source_entity_id,
            target_entity_type, target_entity_id,
            relationship_type, confidence, evidence_json
        )
        SELECT 'symbol', c.id, 'symbol', s.id, 'mocks', 'low', '["mock_patch_by_name"]'
        FROM symbols c, symbols s JOIN files f ON f.id = s.file_id
        WHERE c.file_id = ? AND c.qualified_name = ?
          AND f.project_id = ? AND f.file_kind != 'test'
          AND s.kind = 'method' AND s.name = ?
        """,
        (file_id, caller, project_id, name),
    )


def _patched_symbol(resolver: _PatchTargetResolver, path: str, patch: dict) -> str:
    """The qualified name a patch written in the module at `path` replaces."""
    if "symbol" in patch:
        return patch["symbol"]
    if "target" in patch:
        return resolver.resolve(patch["target"])
    obj = resolver.local(path, patch["object"])
    return resolver.resolve(f"{obj}.{patch['attribute']}")


def _conftest_fixture_patches(
    project_root: Path, path_to_file_id: dict, resolver: _PatchTargetResolver
) -> dict[str, dict]:
    """Per directory, the fixtures its conftest.py defines, with the symbols
    each one's patches replace already resolved where the conftest wrote them."""
    by_directory = {}
    for path in path_to_file_id:
        if Path(path).name != "conftest.py":
            continue
        source = _read_source(Path(project_root) / path)
        try:
            fixtures = extract_fixture_patches(path, source)
        except SyntaxError:
            continue
        by_directory[Path(path).parent.as_posix()] = {
            name: {
                "autouse": fixture["autouse"],
                # The attribute stays for a patch on an object no import names.
                "patches": [
                    {**patch, "symbol": _patched_symbol(resolver, path, patch)}
                    for patch in fixture["patches"]
                ],
            }
            for name, fixture in fixtures.items()
        }
    return by_directory


def refresh_cross_module_edges_for_importers(
    conn: sqlite3.Connection,
    project_root: Path,
    changed_paths: list[str],
    refreshed_paths: list[str],
    path_to_file_id: dict,
    source_roots: list[str],
) -> None:
    """Recompute cross-module edges for unchanged files importing a changed file.

    A changed file's symbols are recreated, which drops the calls and
    attribute-reference edges that pointed into it from files that
    themselves did not change.
    """
    changed_ids = [path_to_file_id[p] for p in changed_paths if p in path_to_file_id]
    if not changed_ids:
        return
    placeholders = ",".join("?" * len(changed_ids))
    importer_ids = {
        row[0]
        for row in conn.execute(
            f"""
            SELECT DISTINCT source_entity_id FROM relationships
            WHERE relationship_type = 'imports'
              AND source_entity_type = 'file' AND target_entity_type = 'file'
              AND target_entity_id IN ({placeholders})
            """,
            changed_ids,
        )
    }
    id_to_path = {file_id: path for path, file_id in path_to_file_id.items()}
    analyses = []
    for importer_id in sorted(importer_ids):
        path = id_to_path.get(importer_id)
        if path is None or path in refreshed_paths:
            continue
        source = _read_source(Path(project_root) / path)
        analysis = _analyze_python_file(path, source)
        analysis["imports"] = resolve_source_root_imports(
            analysis["imports"], source_roots, path_to_file_id
        )
        analyses.append((importer_id, analysis))
    _index_python_cross_file_edges_for_files(conn, analyses, path_to_file_id)


def index_python_test_relationships(
    conn: sqlite3.Connection,
    file_id: int,
    path: str,
    source: str,
    path_to_file_id: dict,
    source_roots: list[str],
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
        (target,) = resolve_source_root_imports(
            [{"module": relationship["target_module"], "level": 0}],
            source_roots,
            path_to_file_id,
        )
        module_path = target["module"].replace(".", "/")
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


def index_python_tests(
    conn: sqlite3.Connection, file_id: int, path: str, source: str
) -> None:
    """Index pytest tests found in a Python file."""
    conn.execute("DELETE FROM tests WHERE file_id = ?", (file_id,))
    tests = discover_tests(path, source)
    for test in tests:
        conn.execute(
            """
            INSERT INTO tests (file_id, test_kind, framework)
            VALUES (?, ?, ?)
            """,
            (file_id, test["kind"], "pytest"),
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


def index_rust_dependencies(
    conn: sqlite3.Connection, project_id: int, project_root: Path
) -> None:
    conn.execute(
        "DELETE FROM dependencies WHERE project_id = ? AND ecosystem = 'rust'",
        (project_id,),
    )
    for dependency in list_dependencies(project_root, ecosystem="rust"):
        status = dependency["version_status"]
        conn.execute(
            """
            INSERT INTO dependencies (
                project_id, name, ecosystem, declared_version, resolved_version
            ) VALUES (?, ?, 'rust', ?, ?)
            """,
            (
                project_id,
                dependency["name"],
                dependency["version"] if status == "declared" else None,
                dependency["version"] if status == "resolved" else None,
            ),
        )


def index_npm_dependencies(
    conn: sqlite3.Connection, project_id: int, project_root: Path
) -> None:
    conn.execute(
        "DELETE FROM dependencies WHERE project_id = ? AND ecosystem = 'npm'",
        (project_id,),
    )
    for dependency in list_dependencies(project_root, ecosystem="npm"):
        status = dependency["version_status"]
        conn.execute(
            """
            INSERT INTO dependencies (
                project_id, name, ecosystem, declared_version, resolved_version
            ) VALUES (?, ?, 'npm', ?, ?)
            """,
            (
                project_id,
                dependency["name"],
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


def run_scan(
    conn: sqlite3.Connection,
    project_root: Path,
    config: ProjectConfig,
    registry: PluginRegistry | None = None,
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

    discovered = discover_files(project_root, config, registry)
    discovered_paths = set()
    changed_python_files = {}
    changed_js_files = {}
    changed_rust_files = {}
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
            source = _read_source(Path(project_root) / record["path"])
            analysis = _analyze_python_file(record["path"], source)
            changed_python_files[record["path"]] = (source, analysis)
            symbols = index_python_symbols(
                conn, file_id, record["path"], source, analysis["symbols"]
            )

            classes = [s for s in symbols if s.get("kind") == "class"]
            if classes:
                module_symbol = next(s for s in symbols if s["kind"] == "module")
                index_python_inheritance_relationships(
                    conn, file_id, module_symbol["qualified_name"], classes
                )
            index_python_call_relationships(conn, file_id, analysis["calls"])
            index_python_self_call_relationships(
                conn, file_id, analysis["self_calls"], symbols
            )
            index_python_typed_call_relationships(
                conn,
                file_id,
                analysis["typed_calls"],
                analysis["imports"],
                path_to_file_id,
                analysis["attribute_calls"],
            )
            index_python_attribute_relationships(
                conn, file_id, analysis["self_references"]
            )
            index_python_class_attribute_relationships(
                conn, file_id, analysis["foreign_accesses"], symbols
            )
            index_python_tests(conn, file_id, record["path"], source)
        elif record["language"] in ("javascript", "typescript"):
            source = _read_source(Path(project_root) / record["path"])
            index_js_symbols(conn, file_id, record["path"], source, record["language"])
            changed_js_files[record["path"]] = extract_js_imports(record["path"], source)
        elif record["language"] == "rust":
            source = _read_source(Path(project_root) / record["path"])
            index_rust_symbols(conn, file_id, record["path"], source)
            index_rust_impl_relationships(conn, file_id, source)
            changed_rust_files[record["path"]] = extract_rust_use(record["path"], source)

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

    cross_file_analyses = []
    for path in paths_to_refresh:
        file_id = path_to_file_id[path]
        if path in changed_python_files:
            source, analysis = changed_python_files[path]
        else:
            source = _read_source(Path(project_root) / path)
            analysis = _analyze_python_file(path, source)
        analysis["imports"] = resolve_source_root_imports(
            analysis["imports"], config.source_roots, path_to_file_id
        )
        index_python_import_relationships(
            conn, file_id, analysis["imports"], path_to_file_id
        )
        cross_file_analyses.append((file_id, analysis))
        index_python_test_relationships(
            conn, file_id, path, source, path_to_file_id, config.source_roots
        )
    _index_python_cross_file_edges_for_files(conn, cross_file_analyses, path_to_file_id)
    if changed_python_files:
        index_django_url_relationships(
            conn, project_id, project_root, path_to_file_id, config.source_roots
        )
        index_mock_patch_relationships(
            conn, project_id, project_root, path_to_file_id, config.source_roots
        )

    js_new_file_added = any(path not in existing_rows for path in changed_js_files)
    if js_new_file_added:
        js_paths_to_refresh = [
            path for path in path_to_file_id
            if Path(path).suffix in (".js", ".jsx", ".ts", ".tsx")
        ]
    else:
        js_paths_to_refresh = list(changed_js_files)

    for path in js_paths_to_refresh:
        file_id = path_to_file_id[path]
        if path in changed_js_files:
            imports = changed_js_files[path]
        else:
            source = _read_source(Path(project_root) / path)
            imports = extract_js_imports(path, source)
        index_js_import_relationships(conn, file_id, path, imports, path_to_file_id)

    rust_new_file_added = any(path not in existing_rows for path in changed_rust_files)
    if rust_new_file_added:
        rust_paths_to_refresh = [
            path for path in path_to_file_id if Path(path).suffix == ".rs"
        ]
    else:
        rust_paths_to_refresh = list(changed_rust_files)

    for path in rust_paths_to_refresh:
        file_id = path_to_file_id[path]
        if path in changed_rust_files:
            uses = changed_rust_files[path]
        else:
            source = _read_source(Path(project_root) / path)
            uses = extract_rust_use(path, source)
        index_rust_use_relationships(conn, file_id, path, uses, path_to_file_id)

    index_python_dependencies(conn, project_id, project_root)
    index_rust_dependencies(conn, project_id, project_root)
    index_npm_dependencies(conn, project_id, project_root)
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
    changed_python_files = {}
    changed_js_files = {}
    changed_rust_files = {}
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

        if record["language"] == "python":
            source = _read_source(Path(project_root) / record["path"])
            analysis = _analyze_python_file(record["path"], source)
            changed_python_files[record["path"]] = (source, analysis)
            symbols = index_python_symbols(
                conn, file_id, record["path"], source, analysis["symbols"]
            )

            classes = [s for s in symbols if s.get("kind") == "class"]
            if classes:
                module_symbol = next(s for s in symbols if s["kind"] == "module")
                index_python_inheritance_relationships(
                    conn, file_id, module_symbol["qualified_name"], classes
                )
            index_python_call_relationships(conn, file_id, analysis["calls"])
            index_python_self_call_relationships(
                conn, file_id, analysis["self_calls"], symbols
            )
            index_python_typed_call_relationships(
                conn,
                file_id,
                analysis["typed_calls"],
                analysis["imports"],
                path_to_file_id,
                analysis["attribute_calls"],
            )
            index_python_attribute_relationships(
                conn, file_id, analysis["self_references"]
            )
            index_python_class_attribute_relationships(
                conn, file_id, analysis["foreign_accesses"], symbols
            )
            index_python_tests(conn, file_id, record["path"], source)
        elif record["language"] in ("javascript", "typescript"):
            source = _read_source(Path(project_root) / record["path"])
            index_js_symbols(conn, file_id, record["path"], source, record["language"])
            changed_js_files[record["path"]] = extract_js_imports(record["path"], source)
        elif record["language"] == "rust":
            source = _read_source(Path(project_root) / record["path"])
            index_rust_symbols(conn, file_id, record["path"], source)
            index_rust_impl_relationships(conn, file_id, source)
            changed_rust_files[record["path"]] = extract_rust_use(record["path"], source)

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

    cross_file_analyses = []
    for path in paths_to_refresh:
        file_id = path_to_file_id[path]
        if path in changed_python_files:
            source, analysis = changed_python_files[path]
        else:
            source = _read_source(Path(project_root) / path)
            analysis = _analyze_python_file(path, source)
        analysis["imports"] = resolve_source_root_imports(
            analysis["imports"], config.source_roots, path_to_file_id
        )
        index_python_import_relationships(
            conn, file_id, analysis["imports"], path_to_file_id
        )
        cross_file_analyses.append((file_id, analysis))
        index_python_test_relationships(
            conn, file_id, path, source, path_to_file_id, config.source_roots
        )
    _index_python_cross_file_edges_for_files(conn, cross_file_analyses, path_to_file_id)

    refresh_cross_module_edges_for_importers(
        conn, project_root, list(changed_python_files), paths_to_refresh, path_to_file_id,
        config.source_roots,
    )
    if changed_python_files:
        index_django_url_relationships(
            conn, project_id, project_root, path_to_file_id, config.source_roots
        )
        index_mock_patch_relationships(
            conn, project_id, project_root, path_to_file_id, config.source_roots
        )

    js_new_file_added = any(path not in existing_rows for path in changed_js_files)
    if js_new_file_added:
        js_paths_to_refresh = [
            path for path in path_to_file_id
            if Path(path).suffix in (".js", ".jsx", ".ts", ".tsx")
        ]
    else:
        js_paths_to_refresh = list(changed_js_files)

    for path in js_paths_to_refresh:
        file_id = path_to_file_id[path]
        if path in changed_js_files:
            imports = changed_js_files[path]
        else:
            source = _read_source(Path(project_root) / path)
            imports = extract_js_imports(path, source)
        index_js_import_relationships(conn, file_id, path, imports, path_to_file_id)

    rust_new_file_added = any(path not in existing_rows for path in changed_rust_files)
    if rust_new_file_added:
        rust_paths_to_refresh = [
            path for path in path_to_file_id if Path(path).suffix == ".rs"
        ]
    else:
        rust_paths_to_refresh = list(changed_rust_files)

    for path in rust_paths_to_refresh:
        file_id = path_to_file_id[path]
        if path in changed_rust_files:
            uses = changed_rust_files[path]
        else:
            source = _read_source(Path(project_root) / path)
            uses = extract_rust_use(path, source)
        index_rust_use_relationships(conn, file_id, path, uses, path_to_file_id)

    index_python_dependencies(conn, project_id, project_root)
    index_rust_dependencies(conn, project_id, project_root)
    index_npm_dependencies(conn, project_id, project_root)
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
