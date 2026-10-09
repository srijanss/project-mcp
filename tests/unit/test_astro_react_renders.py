import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins import treesitter

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0", "astro": "^4.0.0"}}',
    "src/Badge.tsx": (
        "function Pill() {\n  return <i />;\n}\n\n"
        "function Badge() {\n  return <b />;\n}\n\n"
        "export default memo(Badge);\n"
    ),
    "src/Solo.jsx": "export function Solo() {\n  return <p />;\n}\n",
    "src/util.ts": (
        "export function Widget() {\n  return <div />;\n}\n\n"
        "export default function helper() {}\n"
    ),
    "src/pages/index.astro": (
        "---\n"
        "import Tag from '../Badge';\n"
        "import Only from '../Solo.jsx';\n"
        "import Help from '../util';\n"
        "---\n<Tag /><Only /><Help />\n"
    ),
}


@pytest.mark.parametrize("backend", ["tree-sitter", "regex"])
def test_astro_resolves_a_react_default_import_to_the_exported_component_on_either_backend(
    backend, tmp_path, monkeypatch
):
    if backend == "regex":
        monkeypatch.setattr(treesitter, "missing", lambda grammar: "forced off for the test")
    elif treesitter.missing("tsx") is not None:
        pytest.skip("tree-sitter is not installed")
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))

    renders = conn.execute(
        """
        SELECT dst.qualified_name FROM relationships r
        JOIN symbols src ON src.id = r.source_entity_id
        JOIN symbols dst ON dst.id = r.target_entity_id
        WHERE r.relationship_type = 'renders' AND src.qualified_name = 'src.pages.index.index'
        ORDER BY 1
        """
    ).fetchall()
    assert renders == [("src.Badge.Badge",), ("src.Solo.Solo",)]


def test_astro_links_a_named_import_only_to_the_component_exported_under_that_name(tmp_path):
    files = {
        "package.json": FILES["package.json"],
        "src/ui.tsx": (
            "export function Button() {\n  return <button />;\n}\n\n"
            "export function Missing() {\n  return <i />;\n}\n\n"
            "export default function Shell() {\n  return <div />;\n}\n"
        ),
        "src/pages/index.astro": (
            "---\n"
            "import { Button as Btn, Gone, default as Frame } from '../ui';\n"
            "---\n<Btn /><Gone /><Frame />\n"
        ),
    }
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))

    renders = conn.execute(
        """
        SELECT dst.qualified_name FROM relationships r
        JOIN symbols dst ON dst.id = r.target_entity_id
        WHERE r.relationship_type = 'renders' ORDER BY 1
        """
    ).fetchall()
    assert renders == [("src.ui.Button",), ("src.ui.Shell",)]


@pytest.mark.parametrize("backend", ["tree-sitter", "regex"])
def test_astro_links_a_named_import_to_the_component_behind_a_renamed_export(
    backend, tmp_path, monkeypatch
):
    if backend == "regex":
        monkeypatch.setattr(treesitter, "missing", lambda grammar: "forced off for the test")
    elif treesitter.missing("tsx") is not None:
        pytest.skip("tree-sitter is not installed")
    files = {
        "package.json": FILES["package.json"],
        "src/ui.tsx": (
            "function Button() {\n  return <button />;\n}\n\n"
            "function Link() {\n  return <a />;\n}\n\n"
            "export { Button as Primary, Link };\n"
        ),
        "src/pages/index.astro": (
            "---\nimport { Primary, Link as Anchor } from '../ui';\n---\n<Primary /><Anchor />\n"
        ),
    }
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))

    renders = conn.execute(
        """
        SELECT dst.qualified_name FROM relationships r
        JOIN symbols src ON src.id = r.source_entity_id
        JOIN symbols dst ON dst.id = r.target_entity_id
        WHERE r.relationship_type = 'renders' AND src.qualified_name = 'src.pages.index.index'
        ORDER BY 1
        """
    ).fetchall()
    assert renders == [("src.ui.Button",), ("src.ui.Link",)]
