import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins import treesitter
from project_mcp.tools.symbols import get_dependents

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "src/Item.jsx": "export function Item() {\n  return <i />;\n}\n",
    "src/Page.jsx": (
        "import { Item } from './Item';\n\n"
        "export function Page() {\n"
        "  function Item() {\n    return <b />;\n  }\n"
        "  return <Item />;\n}\n"
    ),
}


def _renderers(root, name):
    return [d["source"] for d in get_dependents(root, name) if d["relationship_type"] == "renders"]


@pytest.mark.skipif(treesitter.missing("tsx") is not None, reason="tree-sitter is not installed")
def test_a_tag_naming_a_local_component_that_hides_an_import_renders_the_local_component(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    run_scan(get_connection(tmp_path), tmp_path, load_config(tmp_path))

    assert _renderers(tmp_path, "src.Page.Page.Item") == ["src.Page.Page"]
    assert _renderers(tmp_path, "src.Item.Item") == []
