import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.tools.symbols import get_dependents

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0", "react-router-dom": "^6.0.0"}}',
    "src/ui.tsx": (
        "export function Helper() {\n  return <i />;\n}\n\n"
        "export default function Main() {\n  return <main />;\n}\n"
    ),
    "src/panel.tsx": (
        "function Inner() {\n  return <b />;\n}\n\n"
        "function Other() {\n  return <u />;\n}\n\n"
        "export { Inner as default, Other };\n"
    ),
    "src/App.tsx": (
        "import Helper from './ui';\n"
        "import Panel from './panel';\n"
        "import { createBrowserRouter } from 'react-router-dom';\n\n"
        "export const router = createBrowserRouter([{ path: '/p', element: <Panel /> }]);\n\n"
        "export function App() {\n"
        "  return (\n"
        "    <div>\n"
        "      <Helper />\n"
        "      <Panel />\n"
        "    </div>\n"
        "  );\n"
        "}\n"
    ),
}


def test_a_default_import_links_to_the_exported_default_whatever_its_local_name(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))

    renders = {"source": "src.App.App", "relationship_type": "renders", "confidence": "high"}
    assert get_dependents(tmp_path, "src.ui.Main") == [renders]
    assert get_dependents(tmp_path, "src.ui.Helper") == []
    assert sorted(
        get_dependents(tmp_path, "src.panel.Inner"), key=lambda d: d["relationship_type"]
    ) == [renders, {**renders, "source": "src.App", "relationship_type": "routes_to"}]
    assert get_dependents(tmp_path, "src.panel.Other") == []
    metadata = dict(conn.execute("SELECT name, metadata_json FROM symbols WHERE kind = 'component'"))
    assert json.loads(metadata["Inner"])["routes"] == ["/p"]
