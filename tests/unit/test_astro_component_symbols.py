import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.registry import builtin_registry

FILES = {
    "src/components/Card.astro": '---\nconst note = "<slot />";\n---\n<div>card</div>\n',
    "src/layouts/Base.astro": "<html><body>base</body></html>\n",
    "src/components/Wrapper.astro": "<section><slot /></section>\n",
    "src/pages/index.astro": "---\n---\n<h1>home</h1>\n",
}


def _framework_kinds(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=builtin_registry())
    rows = conn.execute(
        """
        SELECT f.path, s.name, s.metadata_json FROM symbols s
        JOIN files f ON f.id = s.file_id WHERE s.kind = 'component'
        """
    ).fetchall()
    return {path: (name, json.loads(meta)["framework_kind"]) for path, name, meta in rows}


def test_each_astro_file_yields_a_component_or_layout_symbol(tmp_path):
    assert _framework_kinds(tmp_path) == {
        "src/components/Card.astro": ("Card", "astro_component"),
        "src/layouts/Base.astro": ("Base", "astro_layout"),
        "src/components/Wrapper.astro": ("Wrapper", "astro_layout"),
        "src/pages/index.astro": ("index", "astro_component"),
    }
