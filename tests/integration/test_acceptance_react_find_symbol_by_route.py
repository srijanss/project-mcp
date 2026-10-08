from project_mcp.tools.context_packs import get_context_for_feature
from project_mcp.tools.symbols import find_symbol

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0", "react-router-dom": "^6.0.0"}}',
    "src/Users.tsx": "export function Users() {\n  return <ul />;\n}\n",
    "src/Plain.tsx": "export function Plain() {\n  return <i />;\n}\n",
    "src/App.tsx": (
        "import { Routes, Route } from 'react-router-dom';\n"
        "import { Users } from './Users';\n\n"
        "export function App() {\n"
        "  return (\n"
        "    <Routes>\n"
        "      <Route path=\"/users\" element={<Users />} />\n"
        "      <Route path=\"/people\" element={<Users />} />\n"
        "    </Routes>\n"
        "  );\n"
        "}\n"
    ),
}


def _project(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)


def test_find_symbol_resolves_each_react_router_path(tmp_path):
    _project(tmp_path)

    for route in ("/users", "/people"):
        matches = find_symbol(tmp_path, route, kind="component")
        assert [(m["file"], m["name"]) for m in matches] == [("src/Users.tsx", "Users")]


def test_get_context_for_feature_accepts_a_react_router_path(tmp_path):
    _project(tmp_path)

    context = get_context_for_feature(tmp_path, "/people")

    assert "src/Users.tsx" in context["recommended_files_to_open"]


def test_an_unrelated_path_matches_no_route(tmp_path):
    _project(tmp_path)

    assert find_symbol(tmp_path, "/admin", kind="component") == []
