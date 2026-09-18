import json
from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import ensure_fresh_index


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


def get_tests_for(project_root: Path, qualified_name: str) -> list[dict]:
    conn, project_id = _ensure_indexed(project_root)
    entity_type, entity_id = _resolve_entity(conn, project_id, qualified_name)
    if entity_type is None:
        return []

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
