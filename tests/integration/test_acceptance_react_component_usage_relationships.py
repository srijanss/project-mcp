from project_mcp.tools.symbols import get_dependents

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "src/Widget.tsx": "export default function Widget() {\n  return <div />;\n}\n",
    "src/Item.tsx": "export function Item() {\n  return <li />;\n}\n",
    "src/App.tsx": (
        "import React from 'react';\n"
        "import Widget from './Widget';\n"
        "import { Item } from './Item';\n"
        "import { Router } from 'react-router';\n\n"
        "export function App() {\n"
        "  return (\n"
        "    <Router>\n"
        "      <Widget />\n"
        "      <Item />\n"
        "    </Router>\n"
        "  );\n"
        "}\n"
    ),
    "src/Solo.tsx": (
        "function Inner() {\n  return <b />;\n}\n\n"
        "export function Solo() {\n  return <Inner />;\n}\n"
    ),
}


def _write(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)


def test_a_jsx_usage_of_an_imported_component_is_a_renders_relationship(tmp_path):
    _write(tmp_path)

    assert get_dependents(tmp_path, "src.Widget.Widget") == [
        {"source": "src.App.App", "relationship_type": "renders", "confidence": "high"}
    ]
    assert get_dependents(tmp_path, "src.Item.Item") == [
        {"source": "src.App.App", "relationship_type": "renders", "confidence": "high"}
    ]


def test_a_component_used_in_its_own_file_is_linked_but_one_from_a_package_is_not(tmp_path):
    _write(tmp_path)

    assert get_dependents(tmp_path, "src.Solo.Inner") == [
        {"source": "src.Solo.Solo", "relationship_type": "renders", "confidence": "high"}
    ]
    assert get_dependents(tmp_path, "src.App.App") == []
