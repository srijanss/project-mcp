from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.plugins.registry import builtin_registry

FILES = {
    "package.json": '{"dependencies": {"astro": "^4.0.0"}}',
    "src/pages/index.astro": (
        '---\nimport BaseLayout from "../layouts/BaseLayout.astro";\n'
        'import Card from "../components/Card.astro";\n'
        'import Unused from "../components/Unused.astro";\n---\n'
        '<BaseLayout><Card /><Card title="x" /><Missing /></BaseLayout>\n'
    ),
    "src/layouts/BaseLayout.astro": "<html><slot /></html>\n",
    "src/components/Card.astro": '---\nimport Icon from "./Icon.astro";\n---\n<div><Icon /></div>\n',
    "src/components/Icon.astro": "<i />\n",
    "src/components/Unused.astro": "<u />\n",
}


def _renders(conn):
    return sorted(
        conn.execute(
            """
            SELECT source.qualified_name, target.qualified_name FROM relationships r
            JOIN symbols source ON source.id = r.source_entity_id
            JOIN symbols target ON target.id = r.target_entity_id
            WHERE r.relationship_type = 'renders'
              AND r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
            """
        ).fetchall()
    )


def test_template_usages_of_imported_components_are_renders_relationships(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    registry = builtin_registry()

    run_scan(conn, tmp_path, config, registry=registry)
    expected = [
        ("src.components.Card.Card", "src.components.Icon.Icon"),
        ("src.pages.index.index", "src.components.Card.Card"),
        ("src.pages.index.index", "src.layouts.BaseLayout.BaseLayout"),
    ]
    assert _renders(conn) == expected

    refresh_index(conn, tmp_path, config, registry=registry)
    assert _renders(conn) == expected
