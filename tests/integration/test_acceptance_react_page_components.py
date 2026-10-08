import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "pages/index.tsx": "export default function Home() {\n  return <main />;\n}\n",
    "src/pages/about.jsx": "export default function About() {\n  return <main />;\n}\n",
    "app/dashboard/page.tsx": "export default function Dashboard() {\n  return <main />;\n}\n",
    "src/components/Button.tsx": "export function Button() {\n  return <button />;\n}\n",
    "src/components/page.tsx": "export function Pager() {\n  return <nav />;\n}\n",
    "src/homepages/Banner.tsx": "export function Banner() {\n  return <div />;\n}\n",
}


def test_components_in_page_locations_are_tagged_react_page(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    kinds = {
        name: json.loads(meta or "{}").get("framework_kind")
        for name, meta in conn.execute(
            "SELECT name, metadata_json FROM symbols WHERE kind = 'component'"
        )
    }
    assert kinds == {
        "Home": "react_page",
        "About": "react_page",
        "Dashboard": "react_page",
        "Button": "react_component",
        "Pager": "react_component",
        "Banner": "react_component",
    }
