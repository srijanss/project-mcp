"""Cross-file linking of Python files: calls, attribute and constant
references, inheritance and symbol imports between files, plus the test
evidence (pytest tests, tested modules and mock.patch targets) of test files.
"""

import json
import posixpath
import sqlite3
from pathlib import Path

from project_mcp.plugins.python.analyzer import resolve_relative_imports
from project_mcp.plugins.python.mock_patches import (
    extract_fixture_patches,
    extract_mock_patches,
)
from project_mcp.plugins.python.parser import analyze_python_source
from project_mcp.plugins.python.pytest_analyzer import (
    build_test_relationships,
    discover_tests,
)


def _read_source(path: Path) -> str:
    return path.read_text(errors="replace")


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
    # targets are linked by the Python plugin's same-file edges instead.
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
            # Same-file bases are linked by the Python plugin's same-file edges.
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


def _paths_to_relink(context) -> list[str]:
    """The changed files, or every Python file once a file was added.

    A new file can resolve another file's earlier unresolved import.
    """
    return list(context.plugin_paths) if context.added else list(context.changed)


def _project_id(context) -> int:
    file_id = next(iter(context.path_to_file_id.values()))
    return context.conn.execute(
        "SELECT project_id FROM files WHERE id = ?", (file_id,)
    ).fetchone()[0]


def link_cross_file(context) -> None:
    """Link calls, references, inheritance and symbol imports between files."""
    conn, path_to_file_id = context.conn, context.path_to_file_id
    for changed in context.changed.values():
        parsed = changed.analysis.extra
        index_python_typed_call_relationships(
            conn,
            changed.file_id,
            parsed["typed_calls"],
            parsed["imports"],
            path_to_file_id,
            parsed["attribute_calls"],
        )

    paths = _paths_to_relink(context)
    analyses = []
    for path in paths:
        if path in context.changed:
            parsed = context.changed[path].analysis.extra
        else:
            source = _read_source(Path(context.project_root) / path)
            parsed = _analyze_python_file(path, source)
        parsed["imports"] = resolve_source_root_imports(
            parsed["imports"], context.source_roots, path_to_file_id
        )
        analyses.append((path_to_file_id[path], parsed))
    _index_python_cross_file_edges_for_files(conn, analyses, path_to_file_id)
    refresh_cross_module_edges_for_importers(
        conn,
        context.project_root,
        list(context.changed),
        paths,
        path_to_file_id,
        context.source_roots,
    )


def link_test_evidence(context) -> None:
    """Index pytest tests, the modules test files test, and mock.patch targets."""
    conn, path_to_file_id = context.conn, context.path_to_file_id
    for path, changed in context.changed.items():
        index_python_tests(conn, changed.file_id, path, changed.source)
    for path in _paths_to_relink(context):
        if path in context.changed:
            source = context.changed[path].source
        else:
            source = _read_source(Path(context.project_root) / path)
        index_python_test_relationships(
            conn, path_to_file_id[path], path, source, path_to_file_id, context.source_roots
        )
    if context.changed:
        index_mock_patch_relationships(
            conn,
            _project_id(context),
            context.project_root,
            path_to_file_id,
            context.source_roots,
        )
