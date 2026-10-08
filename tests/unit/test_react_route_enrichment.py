import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.registry import builtin_registry

REACT = '{"dependencies": {"react": "^18.0.0"}}'


def _scan(tmp_path, files):
    (tmp_path / "package.json").write_text(REACT)
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=builtin_registry())
    return conn


def _meta(conn, name):
    return json.loads(
        conn.execute("SELECT metadata_json FROM symbols WHERE name = ?", (name,)).fetchone()[0]
    )


def _routes_to(conn):
    return sorted(
        conn.execute(
            """
            SELECT src.qualified_name, dst.qualified_name FROM relationships r
            JOIN symbols src ON src.id = r.source_entity_id
            JOIN symbols dst ON dst.id = r.target_entity_id
            WHERE r.relationship_type = 'routes_to'
            """
        ).fetchall()
    )


USERS = "export default function Users() {\n  return <ul />;\n}\n"


def test_a_component_routed_under_several_paths_lists_them_all(tmp_path):
    conn = _scan(
        tmp_path,
        {
            "src/Users.tsx": USERS,
            "src/App.tsx": (
                "import Users from './Users';\n\n"
                "export function App() {\n  return (\n    <Routes>\n"
                '      <Route path="/users" element={<Users />} />\n'
                '      <Route path="/people" element={<Users />} />\n'
                "    </Routes>\n  );\n}\n"
            ),
        },
    )

    assert _meta(conn, "Users") == {
        "framework_kind": "react_page",
        "routes": ["/people", "/users"],
    }
    assert _routes_to(conn) == [("src.App.App", "src.Users.Users")]


def test_a_route_to_a_component_that_is_not_imported_is_ignored(tmp_path):
    conn = _scan(
        tmp_path,
        {
            "src/Users.tsx": USERS,
            "src/App.tsx": (
                "export function App() {\n"
                '  return <Route path="/users" element={<Users />} />;\n}\n'
            ),
        },
    )

    assert _meta(conn, "Users") == {"framework_kind": "react_component"}
    assert _routes_to(conn) == []


def test_a_rescan_does_not_duplicate_routes_or_relationships(tmp_path):
    files = {
        "src/Users.tsx": USERS,
        "src/App.tsx": (
            "import Users from './Users';\n\n"
            "export function App() {\n"
            '  return <Route path="/users" element={<Users />} />;\n}\n'
        ),
    }
    conn = _scan(tmp_path, files)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=builtin_registry())

    assert _meta(conn, "Users")["routes"] == ["/users"]
    assert _routes_to(conn) == [("src.App.App", "src.Users.Users")]
