import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins import treesitter
from project_mcp.tools.symbols import get_dependents

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "src/Button.jsx": "export function Button() {\n  return <button />;\n}\n",
    "src/Page.jsx": (
        "import { Button } from './Button';\n\n"
        "export function Page({ Button }) {\n  return <Button />;\n}\n"
    ),
    "src/Home.jsx": (
        "import { Button } from './Button';\n\n"
        "export function Home() {\n  return <Button />;\n}\n"
    ),
}


@pytest.mark.skipif(treesitter.missing("tsx") is not None, reason="tree-sitter is not installed")
def test_a_tag_naming_a_parameter_that_hides_an_import_does_not_render_the_import(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    run_scan(get_connection(tmp_path), tmp_path, load_config(tmp_path))

    renderers = [d["source"] for d in get_dependents(tmp_path, "src.Button.Button") if d["relationship_type"] == "renders"]

    assert renderers == ["src.Home.Home"]
