from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.tools.symbols import get_dependents

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "src/badge.tsx": (
        "function Badge() {\n  return <b />;\n}\n\n"
        "function Pill() {\n  return <i />;\n}\n\n"
        "export default memo(/* keep it pure */ Badge);\n"
    ),
    "src/card.tsx": (
        "function Spinner() {\n  return <i />;\n}\n\n"
        "export default memo(\n"
        "  // the card itself\n"
        "  function Card() {\n    return <section />;\n  },\n"
        ");\n"
    ),
    "src/App.tsx": (
        "import Tag from './badge';\n"
        "import Tile from './card';\n\n"
        "export function App() {\n  return <div><Tag /><Tile /></div>;\n}\n"
    ),
}


def test_a_comment_before_the_wrapped_argument_does_not_hide_the_default_export(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))

    renders = {"source": "src.App.App", "relationship_type": "renders", "confidence": "high"}
    assert get_dependents(tmp_path, "src.badge.Badge") == [renders]
    assert get_dependents(tmp_path, "src.badge.Pill") == []
    assert get_dependents(tmp_path, "src.card.Card") == [renders]
    assert get_dependents(tmp_path, "src.card.Spinner") == []
