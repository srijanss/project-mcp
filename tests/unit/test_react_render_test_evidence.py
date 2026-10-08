import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins import treesitter

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "src/Badge.jsx": "export function Badge() {\n  return <b />;\n}\n",
    "src/Tag.jsx": "export function Tag() {\n  return <i />;\n}\n",
    "src/__tests__/Badge.jsx": (
        "import { Badge as B } from '../Badge';\n"
        "import { Tag } from '../Tag';\n\n"
        "it('renders', () => {\n  mount(\n    <B\n      label='x'\n    />,\n  );\n});\n"
    ),
}


def _evidence(conn):
    return dict(
        (name, json.loads(evidence))
        for name, evidence in conn.execute(
            """
            SELECT s.name, r.evidence_json FROM relationships r
            JOIN symbols s ON s.id = r.target_entity_id
            WHERE r.relationship_type = 'tests'
            """
        )
    )


def test_jsx_render_evidence_on_the_regex_backend_keeps_other_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(treesitter, "missing", lambda grammar: "forced off for the test")
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    run_scan(conn, tmp_path, load_config(tmp_path))

    assert _evidence(conn) == {"Badge": ["direct_import", "jsx_render"], "Tag": ["direct_import"]}
