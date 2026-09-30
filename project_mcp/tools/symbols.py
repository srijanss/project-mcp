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


def _symbol_row_to_dict(row: tuple) -> dict:
    return {
        "name": row[0],
        "qualified_name": row[1],
        "kind": row[2],
        "start_line": row[3],
        "end_line": row[4],
        "visibility": row[5],
        "language": row[6],
        "file": row[7],
    }


def find_symbol(
    project_root: Path, query: str, include_migrations: bool = False
) -> list[dict]:
    conn, project_id = _ensure_indexed(project_root)

    like_query = f"%{query.lower()}%"
    # Migrations are generated history that swamps real definitions in results.
    migration_filter = (
        ""
        if include_migrations
        else "AND COALESCE(json_extract(s.metadata_json, '$.framework_kind'), '')"
        " != 'django_migration'"
    )
    rows = conn.execute(
        f"""
        SELECT s.name, s.qualified_name, s.kind, s.start_line, s.end_line,
               s.visibility, s.language, f.path
        FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE f.project_id = ?
          AND (LOWER(s.name) LIKE ? OR LOWER(s.qualified_name) LIKE ?)
          {migration_filter}
        ORDER BY (s.kind = 'field'), s.qualified_name
        """,
        (project_id, like_query, like_query),
    ).fetchall()

    return [_symbol_row_to_dict(row) for row in rows]


def get_symbol_context(project_root: Path, qualified_name: str) -> dict:
    conn, project_id = _ensure_indexed(project_root)

    row = conn.execute(
        """
        SELECT s.name, s.qualified_name, s.kind, s.start_line, s.end_line,
               s.visibility, s.language, f.path
        FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE f.project_id = ? AND s.qualified_name = ?
        """,
        (project_id, qualified_name),
    ).fetchone()

    if row is None:
        return {"found": False, "symbol": None}

    return {"found": True, "symbol": _symbol_row_to_dict(row)}


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


def get_dependencies(project_root: Path, qualified_name: str) -> list[dict]:
    conn, project_id = _ensure_indexed(project_root)
    entity_type, entity_id = _resolve_entity(conn, project_id, qualified_name)
    if entity_type is None:
        return []

    rows = conn.execute(
        """
        SELECT target_entity_type, target_entity_id, relationship_type, confidence
        FROM relationships
        WHERE source_entity_type = ? AND source_entity_id = ?
        """,
        (entity_type, entity_id),
    ).fetchall()

    results = []
    for target_type, target_id, relationship_type, confidence in rows:
        label = _resolve_entity_label(conn, target_type, target_id)
        if label is None:
            continue
        results.append(
            {
                "target": label,
                "relationship_type": relationship_type,
                "confidence": confidence,
            }
        )
    return results


def get_dependents(project_root: Path, qualified_name: str) -> list[dict]:
    conn, project_id = _ensure_indexed(project_root)
    entity_type, entity_id = _resolve_entity(conn, project_id, qualified_name)
    if entity_type is None:
        return []

    rows = conn.execute(
        """
        SELECT source_entity_type, source_entity_id, relationship_type, confidence
        FROM relationships
        WHERE target_entity_type = ? AND target_entity_id = ?
        """,
        (entity_type, entity_id),
    ).fetchall()

    results = []
    for source_type, source_id, relationship_type, confidence in rows:
        label = _resolve_entity_label(conn, source_type, source_id)
        if label is None:
            continue
        results.append(
            {
                "source": label,
                "relationship_type": relationship_type,
                "confidence": confidence,
            }
        )
    return results
