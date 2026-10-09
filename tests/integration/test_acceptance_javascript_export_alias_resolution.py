import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins import treesitter
from project_mcp.tools.symbols import get_dependents
from project_mcp.tools.tests import get_tests_for

BUTTON = "function Button() {\n  return <button />;\n}\n\nexport { Button as Primary, Button as Alt };\n"
FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0", "astro": "^4.0.0"}}',
    "src/Button.jsx": BUTTON,
    "src/pages/index.astro": "---\nimport { Primary } from '../Button.jsx';\n---\n<Primary />\n",
    "src/Toolbar.jsx": (
        "import { Alt as Action } from './Button';\n\n"
        "export function Toolbar() {\n  return <nav><Action /></nav>;\n}\n"
    ),
    "src/Button.test.jsx": (
        "import { Primary } from './Button';\n\ntest('shows', () => {\n  render(<Primary />);\n});\n"
    ),
}


@pytest.fixture(params=["tree-sitter", "regex"])
def root(request, tmp_path, monkeypatch):
    if request.param == "regex":
        monkeypatch.setattr(treesitter, "missing", lambda grammar: "forced off for the test")
    elif treesitter.missing("tsx") is not None:
        pytest.skip("tree-sitter is not installed")
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    run_scan(get_connection(tmp_path), tmp_path, load_config(tmp_path))
    return tmp_path


def _renders(source):
    return {"source": source, "relationship_type": "renders", "confidence": "high"}


def test_an_astro_page_and_a_react_component_importing_renamed_exports_render_the_component(root):
    dependents = get_dependents(root, "src.Button.Button")

    renders = [d for d in dependents if d["relationship_type"] == "renders"]
    assert sorted(renders, key=lambda d: d["source"]) == [
        _renders("src.Toolbar.Toolbar"),
        _renders("src.pages.index.index"),
    ]


def test_a_test_importing_a_renamed_export_is_linked_with_render_evidence(root):
    assert get_tests_for(root, "src.Button.Button") == [
        {"test_file": "src/Button.test.jsx", "confidence": "high", "evidence": ["direct_import", "jsx_render"]}
    ]
