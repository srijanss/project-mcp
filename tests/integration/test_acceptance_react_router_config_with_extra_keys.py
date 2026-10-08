import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.tools.symbols import get_dependents

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0", "react-router-dom": "^6.0.0"}}',
    "src/Users.tsx": "export function Users() {\n  return <ul />;\n}\n",
    "src/Layout.tsx": "export function Layout() {\n  return <main />;\n}\n",
    "src/Detail.tsx": "export function Detail() {\n  return <p />;\n}\n",
    "src/router.tsx": (
        "import { createBrowserRouter } from 'react-router-dom';\n"
        "import { Users } from './Users';\n"
        "import { Layout } from './Layout';\n"
        "import { Detail } from './Detail';\n\n"
        "export const router = createBrowserRouter([\n"
        "  { path: '/users', loader: loadUsers, element: <Users /> },\n"
        "  {\n"
        "    element: <Layout />,\n"
        "    errorElement: null,\n"
        "    path: '/shell',\n"
        "    children: [{ path: 'detail', element: <Detail /> }],\n"
        "  },\n"
        "]);\n"
    ),
}


def test_route_objects_with_other_keys_between_path_and_element_are_still_routes(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))

    components = {
        name: json.loads(meta or "{}")
        for name, meta in conn.execute(
            "SELECT name, metadata_json FROM symbols WHERE kind = 'component'"
        )
    }
    assert components["Users"] == {"framework_kind": "react_page", "routes": ["/users"]}
    assert components["Layout"] == {"framework_kind": "react_page", "routes": ["/shell"]}
    assert components["Detail"] == {"framework_kind": "react_page", "routes": ["detail"]}
    assert get_dependents(tmp_path, "src.Users.Users") == [
        {"source": "src.router", "relationship_type": "routes_to", "confidence": "high"}
    ]
