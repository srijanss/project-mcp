import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.registry import builtin_registry

REACT = '{"dependencies": {"react": "^18.0.0"}}'
TARGET = "export default function Target() {\n  return <p />;\n}\n"
LAZY = (
    "const Target = React.lazy(() => import('./Target'));\n\n"
    "export function Host() {\n  return <Target />;\n}\n"
)


def _write(tmp_path, files):
    (tmp_path / "package.json").write_text(REACT)
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)


def _scan(tmp_path):
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=builtin_registry())
    return conn


def _renders(conn):
    return conn.execute(
        """
        SELECT src.qualified_name, dst.qualified_name, r.confidence FROM relationships r
        JOIN symbols src ON src.id = r.source_entity_id
        JOIN symbols dst ON dst.id = r.target_entity_id
        WHERE r.relationship_type = 'renders'
        """
    ).fetchall()


def _meta(conn, name):
    return json.loads(
        conn.execute("SELECT metadata_json FROM symbols WHERE name = ?", (name,)).fetchone()[0]
    )


def test_a_rescan_does_not_duplicate_low_confidence_relationships(tmp_path):
    _write(tmp_path, {"src/Target.tsx": TARGET, "src/Host.tsx": LAZY})
    conn = _scan(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=builtin_registry())

    assert _renders(conn) == [("src.Host.Host", "src.Target.Target", "low")]


def test_the_partial_mark_goes_when_the_dynamic_pattern_is_removed(tmp_path):
    _write(tmp_path, {"src/Target.tsx": TARGET, "src/Host.tsx": LAZY})
    conn = _scan(tmp_path)
    assert _meta(conn, "Host")["partial"] is True

    (tmp_path / "src/Host.tsx").write_text(
        "import Target from './Target';\n\n"
        "export function Host() {\n  return <Target />;\n}\n"
    )
    conn = _scan(tmp_path)

    assert "partial" not in _meta(conn, "Host")
    assert _renders(conn) == [("src.Host.Host", "src.Target.Target", "high")]
