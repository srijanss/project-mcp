import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins import treesitter
from project_mcp.plugins.astro.framework import AstroFramework
from project_mcp.plugins.react.framework import ReactFramework

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0", "astro": "^4.0.0"}}',
    "src/Widget.tsx": "export default function Widget() {\n  return <div />;\n}\n",
    "src/Item.tsx": "export function Item() {\n  return <li />;\n}\n",
    "src/App.tsx": (
        "import Widget from './Widget';\n"
        "import { Item as Row, type Props } from './Item';\n"
        "// import Ghost from './Ghost';\n\n"
        "export function App() {\n"
        "  const [v] = useState<Props>(null);\n"
        "  return (\n    <Widget>\n      <Row />\n    </Widget>\n  );\n}\n"
    ),
    "src/components/Card.astro": "---\n---\n<div />\n",
    "src/pages/index.astro": (
        "---\n"
        "import Card from '../components/Card.astro';\n"
        "// import Ghost from '../components/Ghost.astro';\n"
        "---\n<Card />\n"
    ),
}


def _renders(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    return conn.execute(
        """
        SELECT src.qualified_name, dst.qualified_name, r.confidence FROM relationships r
        JOIN symbols src ON src.id = r.source_entity_id
        JOIN symbols dst ON dst.id = r.target_entity_id
        WHERE r.relationship_type = 'renders' ORDER BY 1, 2
        """
    ).fetchall()


EXPECTED = [
    ("src.App.App", "src.Item.Item", "high"),
    ("src.App.App", "src.Widget.Widget", "high"),
    ("src.pages.index.index", "src.components.Card.Card", "high"),
]


@pytest.mark.parametrize("backend", ["tree-sitter", "regex"])
def test_react_and_astro_link_the_same_components_on_either_backend(
    backend, tmp_path, monkeypatch
):
    if backend == "regex":
        monkeypatch.setattr(treesitter, "missing", lambda grammar: "forced off for the test")

    assert ReactFramework().backend == backend
    assert AstroFramework().backend == backend
    assert _renders(tmp_path) == EXPECTED


def test_astro_frontmatter_imports_come_from_the_syntax_tree_when_available(
    tmp_path, monkeypatch
):
    from project_mcp.plugins.astro import framework

    def regex_parser_used(script):
        raise AssertionError("the frontmatter was read with the regex parser")

    monkeypatch.setattr(framework, "default_imports", regex_parser_used)

    assert ("src.pages.index.index", "src.components.Card.Card", "high") in _renders(tmp_path)
