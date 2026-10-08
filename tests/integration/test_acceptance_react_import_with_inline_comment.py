from project_mcp.tools.symbols import get_dependents

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "src/Item.tsx": "export function Item() {\n  return <li />;\n}\n",
    "src/Widget.tsx": "export function Widget() {\n  return <b />;\n}\n",
    "src/App.tsx": (
        "import { /* the list row */ Item // and a note\n"
        "} from './Item';\n"
        "import { Widget as W } from './Widget'; // trailing\n\n"
        "export function App() {\n"
        "  return (\n"
        "    <div>\n"
        "      <Item />\n"
        "      <W />\n"
        "    </div>\n"
        "  );\n"
        "}\n"
    ),
}


def test_comments_inside_an_import_list_do_not_break_renders_relationships(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)

    assert get_dependents(tmp_path, "src.Item.Item") == [
        {"source": "src.App.App", "relationship_type": "renders", "confidence": "high"}
    ]
    assert get_dependents(tmp_path, "src.Widget.Widget") == [
        {"source": "src.App.App", "relationship_type": "renders", "confidence": "high"}
    ]
