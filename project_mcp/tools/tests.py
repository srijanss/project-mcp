import json
from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import ensure_fresh_index


MAX_TESTS_NAMED_PER_FILE = 5


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


def _referencing_tests(conn, symbol_id: int) -> list[dict]:
    """Test files whose tests call or read the symbol, with those tests named."""
    rows = conn.execute(
        """
        SELECT f.path, s.qualified_name, r.confidence
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
    for path, test_name, confidence in rows:
        entry = by_file.setdefault(
            path,
            {
                "test_file": path,
                "confidence": "low",
                "evidence": ["symbol_reference"],
                "tests": set(),
            },
        )
        # Helpers and fixtures reach the symbol too; only real tests are named.
        if test_name.rsplit(".", 1)[-1].startswith("test"):
            entry["tests"].add(test_name)
        if confidence == "high":
            entry["confidence"] = "high"
    results = []
    for _, entry in sorted(by_file.items()):
        names = sorted(entry.pop("tests"))
        row = dict(entry)
        if names:
            row["tests"] = names[:MAX_TESTS_NAMED_PER_FILE]
        if len(names) > MAX_TESTS_NAMED_PER_FILE:
            row["tests_total"] = len(names)
        results.append(row)
    return results


def get_tests_for(project_root: Path, qualified_name: str) -> list[dict]:
    conn, project_id = _ensure_indexed(project_root)
    entity_type, entity_id = _resolve_entity(conn, project_id, qualified_name)
    if entity_type is None:
        return []
    if entity_type == "symbol":
        # Tests that name the symbol beat tests that merely import its module.
        referencing = _referencing_tests(conn, entity_id)
        if referencing:
            return referencing

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
