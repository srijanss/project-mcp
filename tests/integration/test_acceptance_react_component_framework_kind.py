import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from tests.golden import copy_fixture


def _framework_kinds(project_root):
    conn = get_connection(project_root)
    run_scan(conn, project_root, load_config(project_root))
    return {
        name: json.loads(metadata or "{}").get("framework_kind")
        for name, metadata in conn.execute(
            "SELECT qualified_name, metadata_json FROM symbols"
            " WHERE kind IN ('component', 'function')"
        )
    }


def test_components_in_a_react_project_get_the_react_component_kind(tmp_path):
    project_root = copy_fixture("react", tmp_path)
    (project_root / "src" / "format.ts").write_text(
        "export function formatLabel(text: string) {\n  return text.trim();\n}\n"
    )

    assert _framework_kinds(project_root) == {
        "src.Widget.Widget": "react_component",
        "src.format.formatLabel": None,
    }


def test_a_project_without_react_leaves_component_like_symbols_untouched(tmp_path):
    (tmp_path / "Widget.js").write_text("export function Widget() {\n  return null;\n}\n")

    assert set(_framework_kinds(tmp_path).values()) <= {None}
