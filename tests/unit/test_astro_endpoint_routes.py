import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.registry import builtin_registry

ENDPOINT = "src/pages/api/data.json.ts"
FILES = {
    ENDPOINT: "export const GET = () => new Response('{}');\n",
    "src/pages/_private.ts": "export const x = 1;\n",
    "src/lib/util.ts": "export const y = 2;\n",
}


def _module_metadata(tmp_path, manifest):
    (tmp_path / "package.json").write_text(manifest)
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=builtin_registry())
    rows = conn.execute(
        """
        SELECT f.path, s.metadata_json FROM symbols s JOIN files f ON f.id = s.file_id
        WHERE s.kind = 'module' AND f.path LIKE '%.ts'
        """
    ).fetchall()
    return {path: json.loads(meta) if meta else {} for path, meta in rows}


def test_ts_and_js_files_under_src_pages_are_endpoints_carrying_their_route(tmp_path):
    modules = _module_metadata(tmp_path, '{"dependencies": {"astro": "^4.0.0"}}')

    assert modules[ENDPOINT]["framework_kind"] == "astro_endpoint"
    assert modules[ENDPOINT]["route"] == "/api/data.json"
    assert modules[ENDPOINT]["route_kind"] == "static"
    assert "framework_kind" not in modules["src/pages/_private.ts"]
    assert "framework_kind" not in modules["src/lib/util.ts"]


def test_projects_without_astro_get_no_endpoint_routes(tmp_path):
    modules = _module_metadata(tmp_path, '{"dependencies": {"react": "^18.0.0"}}')

    assert "framework_kind" not in modules[ENDPOINT]
