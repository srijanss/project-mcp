import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.registry import builtin_registry

REACT = '{"dependencies": {"react": "^18.0.0"}}'


def _framework_kinds(tmp_path, files, manifest=REACT):
    (tmp_path / "package.json").write_text(manifest)
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=builtin_registry())
    return {
        (path, name): json.loads(meta or "{}").get("framework_kind")
        for path, name, meta in conn.execute(
            "SELECT f.path, s.name, s.metadata_json FROM symbols s"
            " JOIN files f ON f.id = s.file_id WHERE s.kind IN ('component', 'function')"
        )
    }


def test_function_and_arrow_components_are_tagged_react_components(tmp_path):
    kinds = _framework_kinds(
        tmp_path,
        {
            "src/Card.tsx": (
                "export function Card() {\n  return <div />;\n}\n\n"
                "export const Badge = () => <span />;\n\n"
                "export function helper() {\n  return 1;\n}\n"
            )
        },
    )

    assert kinds == {
        ("src/Card.tsx", "Card"): "react_component",
        ("src/Card.tsx", "Badge"): "react_component",
        ("src/Card.tsx", "helper"): None,
    }


def test_astro_components_in_a_react_project_are_not_tagged_react(tmp_path):
    kinds = _framework_kinds(
        tmp_path,
        {"src/Hero.astro": "---\nconst a = 1;\n---\n<h1>Hi</h1>\n"},
        manifest='{"dependencies": {"react": "^18.0.0", "astro": "^4.0.0"}}',
    )

    assert set(kinds.values()) <= {None, "astro_component"}
