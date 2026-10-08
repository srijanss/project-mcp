from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.plugins.registry import builtin_registry

PAGE = "src/pages/index.astro"


def _renders(conn):
    return sorted(
        conn.execute(
            """
            SELECT source.qualified_name, target.qualified_name FROM relationships r
            JOIN symbols source ON source.id = r.source_entity_id
            JOIN symbols target ON target.id = r.target_entity_id
            WHERE r.relationship_type = 'renders'
            """
        ).fetchall()
    )


def _project(tmp_path, page, extra=None):
    files = {
        "package.json": '{"dependencies": {"astro": "^4.0.0"}}',
        PAGE: page,
        "src/components/Card.astro": "<div />\n",
        "src/components/Button.tsx": "export const Button = () => null;\n",
        **(extra or {}),
    }
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)


def test_renders_follow_the_template_when_a_page_is_edited(tmp_path):
    card = 'import Card from "../components/Card.astro";'
    _project(tmp_path, f"---\n{card}\n---\n<Card />\n")
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    registry = builtin_registry()
    run_scan(conn, tmp_path, config, registry=registry)
    assert _renders(conn) == [("src.pages.index.index", "src.components.Card.Card")]

    (tmp_path / PAGE).write_text(f"---\n{card}\n---\n<div />\n")
    refresh_index(conn, tmp_path, config, registry=registry)

    assert _renders(conn) == []


def test_only_components_that_are_astro_files_in_the_project_are_rendered(tmp_path):
    page = (
        '---\nimport Button from "../components/Button.tsx";\n'
        'import Gone from "../components/Gone.astro";\n'
        'import Fancy from "fancy-ui";\n---\n<Button /><Gone /><Fancy />\n'
    )
    _project(tmp_path, page)
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path), registry=builtin_registry())

    assert _renders(conn) == []
