"""Spec-named architecture tool wrappers — get_architecture_facts, get_architecture_context."""

from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import ensure_fresh_index


def _fact_row_to_dict(row: tuple) -> dict:
    subject, predicate, obj, origin, source = row
    return {
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "origin": origin,
        "source": source,
    }


def get_architecture_facts(project_root: Path) -> list[dict]:
    project_root = Path(project_root)
    config = load_config(project_root)
    conn = get_connection(project_root)
    ensure_fresh_index(conn, project_root, config)

    rows = conn.execute(
        "SELECT subject, predicate, object, origin, source FROM architecture_facts"
    ).fetchall()
    return [_fact_row_to_dict(row) for row in rows]


def get_architecture_context(project_root: Path, area: str | None = None) -> dict:
    facts = get_architecture_facts(project_root)

    if area is not None:
        area_lower = area.lower()
        facts = [
            fact
            for fact in facts
            if area_lower in fact["subject"].lower() or area_lower in fact["object"].lower()
        ]

    return {
        "target": area,
        "type": "architecture",
        "facts": facts,
    }
