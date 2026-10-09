from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0", "astro": "^4.0.0"}}',
    "src/Card.tsx": "export default function Card() {\n  return <b />;\n}\n",
    "src/Card.jsx": "export default function Card() {\n  return <i />;\n}\n",
    "src/pages/index.astro": "---\nimport Card from '../Card';\n---\n<Card />\n",
}


def test_an_extensionless_import_renders_only_the_file_import_resolution_picks(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))

    rendered_files = [
        path
        for (path,) in conn.execute(
            """
            SELECT f.path FROM relationships r
            JOIN symbols dst ON dst.id = r.target_entity_id
            JOIN files f ON f.id = dst.file_id
            WHERE r.relationship_type = 'renders'
            """
        )
    ]
    imported_files = [
        path
        for (path,) in conn.execute(
            """
            SELECT f.path FROM relationships r
            JOIN files f ON f.id = r.target_entity_id
            WHERE r.relationship_type = 'imports' AND r.target_entity_type = 'file'
            """
        )
    ]

    assert rendered_files == imported_files == ["src/Card.tsx"]
