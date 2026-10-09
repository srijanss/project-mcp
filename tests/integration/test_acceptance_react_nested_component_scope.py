import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins import treesitter
from project_mcp.tools.symbols import get_dependents

TABLE = (
    "function Row() {\n  return <tr />;\n}\n\n"
    "export function Table() {\n  return <table><Row /></table>;\n}\n\n"
    "export function Outer() {\n"
    "  function Row() {\n    return <td />;\n  }\n"
    "  return <div><Row /></div>;\n"
    "}\n"
)


def _renders(source):
    return {"source": source, "relationship_type": "renders", "confidence": "high"}


@pytest.mark.skipif(treesitter.missing("tsx") is not None, reason="tree-sitter is not installed")
def test_a_tag_renders_the_component_visible_from_where_it_is_used(tmp_path):
    files = {"package.json": '{"dependencies": {"react": "^18.0.0"}}', "src/Table.tsx": TABLE}
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    run_scan(get_connection(tmp_path), tmp_path, load_config(tmp_path))

    assert get_dependents(tmp_path, "src.Table.Row") == [_renders("src.Table.Table")]
    assert get_dependents(tmp_path, "src.Table.Outer.Row") == [_renders("src.Table.Outer")]
