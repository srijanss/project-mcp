from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.tools.symbols import get_dependents

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0", "astro": "^4.0.0"}}',
    "src/components/Badge.tsx": (
        "function Pill() {\n  return <i />;\n}\n\n"
        "export default function Badge() {\n  return <b><Pill /></b>;\n}\n"
    ),
    "src/components/Card.tsx": "export default function Card() {\n  return <div />;\n}\n",
    "src/pages/index.astro": (
        "---\n"
        "import Tag from '../components/Badge';\n"
        "import Card from '../components/Card';\n"
        "---\n<main><Tag /></main>\n"
    ),
    "src/layouts/Base.astro": (
        "---\nimport Label from '../components/Badge.tsx';\n---\n<Label /><slot />\n"
    ),
}


def _scan(tmp_path, extra=None):
    for path, text in {**FILES, **(extra or {})}.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    return conn


def _renders(source):
    return {"source": source, "relationship_type": "renders", "confidence": "high"}


def test_an_astro_page_and_layout_render_the_default_exported_react_component(tmp_path):
    _scan(tmp_path)

    dependents = sorted(get_dependents(tmp_path, "src.components.Badge.Badge"), key=lambda d: d["source"])
    assert dependents == [_renders("src.layouts.Base.Base"), _renders("src.pages.index.index")]
    assert get_dependents(tmp_path, "src.components.Badge.Pill") == [
        _renders("src.components.Badge.Badge")
    ]


def test_importing_a_react_component_without_rendering_it_is_no_renders_edge(tmp_path):
    _scan(tmp_path)

    assert get_dependents(tmp_path, "src.components.Card.Card") == []


def test_refresh_removes_a_deleted_astro_usage_of_a_react_component(tmp_path):
    conn = _scan(tmp_path)
    page = tmp_path / "src/pages/index.astro"
    page.write_text(page.read_text().replace("<Tag />", ""))
    refresh_index(conn, tmp_path, load_config(tmp_path))

    assert get_dependents(tmp_path, "src.components.Badge.Badge") == [_renders("src.layouts.Base.Base")]


def test_without_the_react_plugin_astro_still_links_the_javascript_component(tmp_path):
    _scan(tmp_path, {"mcpctl.toml": '[plugins]\ndisabled = ["react"]\n'})

    dependents = sorted(get_dependents(tmp_path, "src.components.Badge.Badge"), key=lambda d: d["source"])
    assert dependents == [_renders("src.layouts.Base.Base"), _renders("src.pages.index.index")]
