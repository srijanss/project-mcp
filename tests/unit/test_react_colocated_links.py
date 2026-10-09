import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "src/theme.js": "export function color() {\n  return 'red';\n}\n",
    "src/Badge.jsx": "export function Badge() {\n  return <b />;\n}\n",
    "src/Badge.spec.jsx": "import { color } from './theme';\n\nit('is red', () => color());\n",
}


def _links(conn):
    rows = conn.execute(
        """
        SELECT f.path, COALESCE(s.qualified_name, tf.path), r.confidence, r.evidence_json
        FROM relationships r
        JOIN files f ON f.id = r.source_entity_id
        LEFT JOIN symbols s ON r.target_entity_type = 'symbol' AND s.id = r.target_entity_id
        LEFT JOIN files tf ON r.target_entity_type = 'file' AND tf.id = r.target_entity_id
        WHERE r.relationship_type = 'tests'
        ORDER BY 2
        """
    ).fetchall()
    return [(path, target, confidence, json.loads(evidence)) for path, target, confidence, evidence in rows]


def test_colocated_links_survive_reindexing_the_component_and_sit_beside_other_imports(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    component = tmp_path / "src/Badge.jsx"
    component.write_text(component.read_text() + "\nexport const SIZE = 1;\n")
    refresh_index(conn, tmp_path, load_config(tmp_path))
    run_scan(conn, tmp_path, load_config(tmp_path))

    assert _links(conn) == [
        ("src/Badge.spec.jsx", "src.Badge.Badge", "low", ["naming_convention"]),
        ("src/Badge.spec.jsx", "src.theme.color", "high", ["direct_import"]),
    ]
