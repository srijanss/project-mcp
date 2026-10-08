import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.plugins import treesitter
from project_mcp.tools.symbols import get_dependents

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0", "astro": "^4.0.0"}}',
    "src/components/ui.tsx": (
        "export function Button() {\n  return <button />;\n}\n\n"
        "export function Link() {\n  return <a />;\n}\n\n"
        "export function Other() {\n  return <i />;\n}\n\n"
        "export default function Shell() {\n  return <div />;\n}\n"
    ),
    "src/pages/index.astro": (
        "---\n"
        "import { Button, Link as Anchor } from '../components/ui';\n"
        "---\n<main><Button /><Anchor /></main>\n"
    ),
}


@pytest.fixture(params=["tree-sitter", "regex"])
def project(request, tmp_path, monkeypatch):
    if request.param == "regex":
        monkeypatch.setattr(treesitter, "missing", lambda grammar: "forced off for the test")
    elif treesitter.missing("tsx") is not None:
        pytest.skip("tree-sitter is not installed")
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    return tmp_path, conn


RENDERED_BY_INDEX = [
    {"source": "src.pages.index.index", "relationship_type": "renders", "confidence": "high"}
]


def test_an_astro_template_renders_named_and_aliased_react_imports(project):
    root, _ = project

    assert get_dependents(root, "src.components.ui.Button") == RENDERED_BY_INDEX
    assert get_dependents(root, "src.components.ui.Link") == RENDERED_BY_INDEX
    assert get_dependents(root, "src.components.ui.Other") == []
    assert get_dependents(root, "src.components.ui.Shell") == []


def test_refresh_removes_a_deleted_named_import_usage(project):
    root, conn = project
    page = root / "src/pages/index.astro"
    page.write_text(page.read_text().replace("<Anchor />", ""))
    refresh_index(conn, root, load_config(root))

    assert get_dependents(root, "src.components.ui.Button") == RENDERED_BY_INDEX
    assert get_dependents(root, "src.components.ui.Link") == []
