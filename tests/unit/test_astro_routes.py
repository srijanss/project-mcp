import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.registry import builtin_registry

FILES = {
    "package.json": '{"dependencies": {"astro": "^4.0.0"}}',
    "src/pages/index.astro": "<h1>home</h1>\n",
    "src/pages/about.astro": "<h1>about</h1>\n",
    "src/pages/blog/[slug].astro": "<h1>post</h1>\n",
    "src/pages/docs/[...path].astro": "<h1>docs</h1>\n",
    "src/pages/api/data.json.ts": "export const GET = () => new Response('{}');\n",
    "src/pages/_hidden.astro": "<p>not a route</p>\n",
    "src/components/Card.astro": "<div>card</div>\n",
}


def _routes(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=builtin_registry())
    rows = conn.execute(
        """
        SELECT f.path, s.metadata_json FROM symbols s JOIN files f ON f.id = s.file_id
        WHERE s.kind = 'component' OR (s.kind = 'module' AND f.path LIKE '%.ts')
        """
    ).fetchall()
    found = {}
    for path, meta in rows:
        meta = json.loads(meta) if meta else {}
        found[path] = (meta.get("framework_kind"), meta.get("route"), meta.get("route_kind"))
    return found


def test_files_under_src_pages_resolve_to_routes(tmp_path):
    assert _routes(tmp_path) == {
        "src/pages/index.astro": ("astro_page", "/", "static"),
        "src/pages/about.astro": ("astro_page", "/about", "static"),
        "src/pages/blog/[slug].astro": ("astro_page", "/blog/[slug]", "dynamic"),
        "src/pages/docs/[...path].astro": ("astro_page", "/docs/[...path]", "rest"),
        "src/pages/api/data.json.ts": ("astro_endpoint", "/api/data.json", "static"),
        "src/pages/_hidden.astro": ("astro_component", None, None),
        "src/components/Card.astro": ("astro_component", None, None),
    }
