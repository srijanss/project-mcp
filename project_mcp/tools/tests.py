import json
from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import ensure_fresh_index


MAX_TESTS_NAMED_PER_FILE = 5
MAX_INDIRECT_CALL_HOPS = 3


def _current_project_id(conn, project_root: Path) -> int | None:
    row = conn.execute(
        "SELECT id FROM projects WHERE root_path = ?", (str(project_root),)
    ).fetchone()
    return row[0] if row else None


def _ensure_indexed(project_root: Path):
    project_root = Path(project_root)
    config = load_config(project_root)
    conn = get_connection(project_root)

    ensure_fresh_index(conn, project_root, config)

    return conn, _current_project_id(conn, project_root)


def _resolve_entity(conn, project_id: int, qualified_name: str):
    module_row = conn.execute(
        """
        SELECT f.id FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE f.project_id = ? AND s.kind = 'module' AND s.qualified_name = ?
        """,
        (project_id, qualified_name),
    ).fetchone()
    if module_row:
        return "file", module_row[0]

    symbol_row = conn.execute(
        """
        SELECT s.id FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE f.project_id = ? AND s.qualified_name = ?
        """,
        (project_id, qualified_name),
    ).fetchone()
    if symbol_row:
        return "symbol", symbol_row[0]

    return None, None


def _resolve_entity_label(conn, entity_type: str, entity_id: int):
    if entity_type == "file":
        row = conn.execute(
            "SELECT path FROM files WHERE id = ?", (entity_id,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT qualified_name FROM symbols WHERE id = ?", (entity_id,)
        ).fetchone()
    return row[0] if row else None


def _capped(names: list[str], limit: int) -> list[str]:
    return names[:limit] if limit else names


def _limited(row: dict, limit: int) -> dict:
    """The row with its named tests, mocked tests and each path's, cut to `limit`."""
    mocked = row.get("mocked")
    if mocked:
        row = {**row, "mocked": _capped(mocked, limit)}
        if len(row["mocked"]) < len(mocked):
            row["mocked_total"] = len(mocked)
    names = row.get("tests")
    if not names:
        return row
    if "paths" in row:
        # Each path is cut to `limit`; the top-level list names every test, so
        # none is reachable only through a path.
        return {
            **row,
            "paths": [
                {**path, "tests": _capped(path["tests"], limit)} for path in row["paths"]
            ],
        }
    row = {**row, "tests": _capped(names, limit)}
    if len(row["tests"]) < len(names):
        row["tests_total"] = len(names)
    return row


def _referencing_tests(conn, symbol_id: int) -> list[dict]:
    """Test files whose tests call or read the symbol, with those tests named."""
    rows = conn.execute(
        """
        SELECT f.path, s.qualified_name, s.kind, r.confidence, r.evidence_json
        FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN files f ON f.id = s.file_id
        WHERE r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND r.target_entity_id = ? AND r.relationship_type IN ('calls', 'references')
          AND f.file_kind = 'test'
        """,
        (symbol_id,),
    ).fetchall()
    by_file: dict[str, dict] = {}
    for path, test_name, kind, confidence, evidence_json in rows:
        entry = by_file.setdefault(
            path,
            {
                "test_file": path,
                "confidence": "low",
                "evidence": [],
                "tests": set(),
            },
        )
        for evidence in json.loads(evidence_json or '["symbol_reference"]'):
            if evidence not in entry["evidence"]:
                entry["evidence"].append(evidence)
        # Helpers and fixtures reach the symbol too; only real tests are named.
        is_test = kind in ("function", "method")
        if is_test and test_name.rsplit(".", 1)[-1].startswith("test"):
            entry["tests"].add(test_name)
        if confidence == "high":
            entry["confidence"] = "high"
    results = []
    for _, entry in sorted(by_file.items()):
        names = sorted(entry.pop("tests"))
        row = dict(entry)
        if names:
            row["tests"] = names
        else:
            # Only helpers reach the symbol: the file exercises it, but no test
            # names it. A guessed (low) link stays low.
            if row["confidence"] == "high":
                row["confidence"] = "medium"
            row["evidence"] = ["helper_reference"]
        results.append(row)
    return results


def _mocked_symbols(conn, test_names: list[str]) -> dict[str, set[int]]:
    """The symbols each named test replaces with a mock while it runs: a
    mocked class takes its methods with it."""
    rows = conn.execute(
        f"""
        SELECT s.qualified_name, m.id
        FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        JOIN symbols m ON m.file_id = t.file_id
          AND (m.id = t.id OR substr(m.qualified_name, 1, length(t.qualified_name) + 1)
                              = t.qualified_name || '.')
        WHERE r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND r.relationship_type = 'mocks'
          AND s.qualified_name IN ({", ".join("?" * len(test_names))})
        """,
        test_names,
    ).fetchall()
    mocked: dict[str, set[int]] = {}
    for test_name, target_id in rows:
        mocked.setdefault(test_name, set()).add(target_id)
    return mocked


def _set_aside_mocked(conn, row: dict, symbol_id: int) -> dict:
    """The row with its tests that mock the symbol itself moved to `mocked`."""
    if "tests" not in row:
        return row
    mocks = _mocked_symbols(conn, row["tests"])
    mocked = [name for name in row["tests"] if symbol_id in mocks.get(name, set())]
    if not mocked:
        return row
    tests = [name for name in row["tests"] if name not in mocked]
    if tests:
        return {**row, "tests": tests, "mocked": mocked}
    return _only_mocked(row, mocked)


def _only_mocked(row: dict, mocked: list[str]) -> dict:
    """A file whose every test reaching the symbol mocks it (or its path) away."""
    return {
        "test_file": row["test_file"],
        "confidence": "low",
        "evidence": [*row["evidence"], "mocked"],
        "mocked": mocked,
    }


def _taking_turns(groups: list[list[str]]) -> list[str]:
    """Each group's first name, then each one's second, ...: a capped prefix
    still names a test from every group it can."""
    names = []
    for depth in range(max(map(len, groups), default=0)):
        names.extend(group[depth] for group in groups if depth < len(group))
    return names


def _indirect_tests(conn, symbol_id: int, through_test_helpers: bool = False) -> list[dict]:
    """Tests that reach the symbol only through the code calling it, nearest first.

    `through_test_helpers` walks the helpers in test files instead of app code.
    """
    caller_files = "f.file_kind = 'test'" if through_test_helpers else "f.file_kind != 'test'"
    evidence = "helper_call" if through_test_helpers else "indirect_call"
    # Each test file collects every call path into it; a test is credited to
    # the nearest path that reaches it. A test mocking a symbol on the path
    # never runs the real symbol through it, so it is set aside as mocked.
    paths_by_file: dict[str, list[dict]] = {}
    mocked_by_file: dict[str, set[str]] = {}
    # A caller is revisited when another chain reaches it: a test mocking one
    # branch of a diamond still runs the symbol through the other.
    seen = {(symbol_id, frozenset({symbol_id}))}
    frontier = [(symbol_id, [], {symbol_id})]
    for _ in range(MAX_INDIRECT_CALL_HOPS):
        next_frontier = []
        for callee_id, chain, chain_ids in frontier:
            callers = conn.execute(
                f"""
                SELECT s.id, s.qualified_name
                FROM relationships r
                JOIN symbols s ON s.id = r.source_entity_id
                JOIN files f ON f.id = s.file_id
                WHERE r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
                  AND r.target_entity_id = ? AND r.relationship_type = 'calls'
                  AND {caller_files}
                ORDER BY s.qualified_name
                """,
                (callee_id,),
            ).fetchall()
            for caller_id, caller_name in callers:
                via_ids = {caller_id, *chain_ids}
                if caller_id in chain_ids or (caller_id, frozenset(via_ids)) in seen:
                    continue
                seen.add((caller_id, frozenset(via_ids)))
                via = [caller_name, *chain]
                for row in _referencing_tests(conn, caller_id):
                    if "tests" not in row:
                        continue
                    paths = paths_by_file.setdefault(row["test_file"], [])
                    mocked = mocked_by_file.setdefault(row["test_file"], set())
                    credited = {name for path in paths for name in path["tests"]}
                    mocks = _mocked_symbols(conn, row["tests"])
                    tests = []
                    for name in row["tests"]:
                        if mocks.get(name, set()) & via_ids:
                            mocked.add(name)
                        elif name not in credited:
                            tests.append(name)
                    if tests:
                        paths.append({"via": via, "tests": tests})
                next_frontier.append((caller_id, via, via_ids))
        frontier = next_frontier

    results = []
    for test_file, paths in paths_by_file.items():
        if not paths:
            row = {"test_file": test_file, "evidence": [evidence]}
            results.append(_only_mocked(row, sorted(mocked_by_file[test_file])))
            continue
        row = {
            "test_file": test_file,
            "confidence": "medium",
            "evidence": [evidence],
            "via": paths[0]["via"],
            "tests": _taking_turns([path["tests"] for path in paths]),
        }
        if len(paths) > 1:
            row["paths"] = paths
        mocked = mocked_by_file[test_file] - set(row["tests"])
        if mocked:
            row["mocked"] = sorted(mocked)
        results.append(row)
    return results


def get_tests_for(
    project_root: Path, qualified_name: str, limit: int = MAX_TESTS_NAMED_PER_FILE
) -> list[dict]:
    """Test files covering a module or symbol; `limit=0` names every test per file."""
    if limit < 0:
        raise ValueError(f"limit must be 0 or more, got {limit}")
    conn, project_id = _ensure_indexed(project_root)
    entity_type, entity_id = _resolve_entity(conn, project_id, qualified_name)
    if entity_type is None:
        return []
    if entity_type == "symbol":
        # Tests that name the symbol beat tests that merely import its module.
        by_file = {
            row["test_file"]: _set_aside_mocked(conn, row, entity_id)
            for row in _referencing_tests(conn, entity_id)
        }
        for row in _indirect_tests(conn, entity_id, through_test_helpers=True):
            existing = by_file.get(row["test_file"], {})
            if "tests" not in existing:
                by_file[row["test_file"]] = row
            elif "tests" not in row:
                # Every helper test mocks the symbol: set aside beside the direct tests.
                existing["mocked"] = list(dict.fromkeys([*existing.get("mocked", []), *row["mocked"]]))
            else:
                # Tests calling the symbol come before those using a helper.
                existing["tests"] = list(dict.fromkeys([*existing["tests"], *row["tests"]]))
                existing["evidence"] = [*existing["evidence"], "helper_call"]
        if by_file:
            return [_limited(by_file[path], limit) for path in sorted(by_file)]
        indirect = _indirect_tests(conn, entity_id)
        if indirect:
            return [_limited(row, limit) for row in indirect]

    rows = conn.execute(
        """
        SELECT source_entity_type, source_entity_id, confidence, evidence_json
        FROM relationships
        WHERE target_entity_type = ? AND target_entity_id = ?
          AND relationship_type = 'tests'
        """,
        (entity_type, entity_id),
    ).fetchall()

    results = []
    for source_type, source_id, confidence, evidence_json in rows:
        label = _resolve_entity_label(conn, source_type, source_id)
        if label is None:
            continue
        results.append(
            {
                "test_file": label,
                "confidence": confidence,
                "evidence": json.loads(evidence_json) if evidence_json else [],
            }
        )
    return results


def get_test_summary(project_root: Path) -> dict:
    conn, project_id = _ensure_indexed(project_root)

    total_tests = conn.execute(
        """
        SELECT COUNT(*) FROM tests t
        JOIN files f ON f.id = t.file_id
        WHERE f.project_id = ?
        """,
        (project_id,),
    ).fetchone()[0]

    rows = conn.execute(
        """
        SELECT r.confidence, COUNT(*)
        FROM relationships r
        JOIN files f ON f.id = r.source_entity_id AND r.source_entity_type = 'file'
        WHERE f.project_id = ? AND r.relationship_type = 'tests'
        GROUP BY r.confidence
        """,
        (project_id,),
    ).fetchall()
    by_confidence = {confidence: count for confidence, count in rows}

    return {
        "total_tests": total_tests,
        "total_relationships": sum(by_confidence.values()),
        "by_confidence": by_confidence,
    }
