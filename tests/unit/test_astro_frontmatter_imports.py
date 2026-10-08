from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.registry import builtin_registry

PAGE = "src/pages/index.astro"


def _imported_files(tmp_path):
    for path, text in {
        PAGE: (
            '---\nimport Layout from "../layouts/Layout.astro";\n'
            'import { fmt } from "../utils/format";\n'
            'import data from "../data.js";\n'
            'import { getCollection } from "astro:content";\n'
            'import React from "react";\n---\n<Layout />\n'
        ),
        "src/layouts/Layout.astro": "---\n---\n<slot />\n",
        "src/utils/format.ts": "export const fmt = (x: number) => String(x);\n",
        "src/data.js": "export default [];\n",
    }.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=builtin_registry())
    return {
        row[0]
        for row in conn.execute(
            """
            SELECT target.path FROM relationships r
            JOIN files source ON source.id = r.source_entity_id
            JOIN files target ON target.id = r.target_entity_id
            WHERE r.relationship_type = 'imports' AND source.path = ?
            """,
            (PAGE,),
        )
    }


def test_frontmatter_imports_resolve_to_project_astro_ts_and_js_files(tmp_path):
    assert _imported_files(tmp_path) == {
        "src/layouts/Layout.astro",
        "src/utils/format.ts",
        "src/data.js",
    }
