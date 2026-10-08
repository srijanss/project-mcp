import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.tools.symbols import get_dependents

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0", "react-router-dom": "^6.0.0"}}',
    "src/Users.tsx": "export default function Users() {\n  return <ul />;\n}\n",
    "src/Home.tsx": "export function Home() {\n  return <main />;\n}\n",
    "src/About.tsx": "export function About() {\n  return <main />;\n}\n",
    "src/Plain.tsx": "export function Plain() {\n  return <i />;\n}\n",
    "src/App.tsx": (
        "import { Routes, Route } from 'react-router-dom';\n"
        "import Users from './Users';\n\n"
        "export function App() {\n"
        "  return (\n"
        "    <Routes>\n"
        "      <Route path=\"/users\" element={<Users />} />\n"
        "    </Routes>\n"
        "  );\n"
        "}\n"
    ),
    "src/router.tsx": (
        "import { createBrowserRouter } from 'react-router-dom';\n"
        "import { Home } from './Home';\n"
        "import { About } from './About';\n\n"
        "export const router = createBrowserRouter([\n"
        "  { path: '/', element: <Home /> },\n"
        "  { path: '/about', element: <About /> },\n"
        "]);\n"
    ),
}


def _scan(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    return {
        name: json.loads(meta or "{}")
        for name, meta in conn.execute(
            "SELECT name, metadata_json FROM symbols WHERE kind = 'component'"
        )
    }


def test_statically_visible_routes_become_route_metadata_on_the_target_component(tmp_path):
    components = _scan(tmp_path)

    assert components["Users"] == {"framework_kind": "react_page", "routes": ["/users"]}
    assert components["Home"] == {"framework_kind": "react_page", "routes": ["/"]}
    assert components["About"] == {"framework_kind": "react_page", "routes": ["/about"]}
    assert components["Plain"] == {"framework_kind": "react_component"}


def test_a_routed_component_gets_a_routes_to_relationship_from_the_declaring_code(tmp_path):
    _scan(tmp_path)

    assert sorted(
        get_dependents(tmp_path, "src.Users.Users"), key=lambda d: d["relationship_type"]
    ) == [
        {"source": "src.App.App", "relationship_type": "renders", "confidence": "high"},
        {"source": "src.App.App", "relationship_type": "routes_to", "confidence": "high"},
    ]
    assert get_dependents(tmp_path, "src.About.About") == [
        {"source": "src.router", "relationship_type": "routes_to", "confidence": "high"}
    ]
