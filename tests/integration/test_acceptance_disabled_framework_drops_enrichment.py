from project_mcp.tools.symbols import get_dependents

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "src/Button.jsx": "export function Button() {\n  return <button />;\n}\n",
    "src/Page.jsx": (
        "import { Button } from './Button';\n\n"
        "export function Page() {\n  return <Button />;\n}\n"
    ),
}


def _renderers(root):
    return [d["source"] for d in get_dependents(root, "src.Button.Button") if d["relationship_type"] == "renders"]


def test_disabling_a_framework_plugin_drops_the_relationships_it_added_to_unchanged_files(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    assert _renderers(tmp_path) == ["src.Page.Page"]

    (tmp_path / "mcpctl.toml").write_text('[plugins]\ndisabled = ["react"]\n')

    assert _renderers(tmp_path) == []
