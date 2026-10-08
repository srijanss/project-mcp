from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.tools.symbols import get_dependents

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "src/badge.tsx": (
        "import { memo } from 'react';\n\n"
        "function Pill() {\n  return <i />;\n}\n\n"
        "export default memo(function Badge() {\n"
        "  return <b><Pill /></b>;\n"
        "});\n"
    ),
    "src/App.tsx": (
        "import Tag from './badge';\n\n"
        "export function App() {\n  return <Tag />;\n}\n"
    ),
}


def test_a_default_import_links_to_a_named_function_wrapped_in_the_default_export(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))

    renders = {"source": "src.App.App", "relationship_type": "renders", "confidence": "high"}
    assert get_dependents(tmp_path, "src.badge.Badge") == [renders]
    assert get_dependents(tmp_path, "src.badge.Pill") == []
    kinds = dict(conn.execute("SELECT name, kind FROM symbols WHERE name IN ('Badge', 'Pill')"))
    assert kinds == {"Badge": "component", "Pill": "component"}
