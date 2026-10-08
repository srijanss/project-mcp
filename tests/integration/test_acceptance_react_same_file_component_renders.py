import json

import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.plugins import treesitter
from project_mcp.tools.symbols import get_dependents

PAGE = (
    "import { memo, forwardRef } from 'react';\n\n"
    "export function Page() {\n"
    "  return <main><Header /><Card /><Field /><Footer /></main>;\n"
    "}\n\n"
    "function Header() {\n  return <h1 />;\n}\n\n"
    "const Card = memo(function Card() {\n  return <div />;\n});\n\n"
    "const Field = forwardRef((props, ref) => <input ref={ref} />);\n\n"
    "const Footer = () => <footer />;\n"
)
LIST = (
    "function Row() {\n  return <li />;\n}\n\n"
    "export function List({ Row }) {\n  return <ul><Row /></ul>;\n}\n\n"
    "export function Table() {\n  return <table><Row /></table>;\n}\n"
)


def _scan(tmp_path, files):
    files = {"package.json": '{"dependencies": {"react": "^18.0.0"}}', **files}
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    return conn


def _renders(source, confidence="high"):
    return {"source": source, "relationship_type": "renders", "confidence": confidence}


@pytest.mark.skipif(treesitter.missing("tsx") is not None, reason="tree-sitter is not installed")
def test_jsx_renders_a_component_declared_in_the_same_file(tmp_path):
    _scan(tmp_path, {"src/Page.tsx": PAGE})

    for name in ("Header", "Card", "Field", "Footer"):
        assert get_dependents(tmp_path, f"src.Page.{name}") == [_renders("src.Page.Page")]


@pytest.mark.skipif(treesitter.missing("tsx") is not None, reason="tree-sitter is not installed")
def test_a_shadowed_component_name_creates_no_edge(tmp_path):
    _scan(tmp_path, {"src/List.tsx": LIST})

    assert get_dependents(tmp_path, "src.List.Row") == [_renders("src.List.Table")]


def test_without_scopes_the_regex_parser_links_a_shadowed_name_with_low_confidence(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(treesitter, "missing", lambda grammar: "forced off")
    conn = _scan(tmp_path, {"src/List.tsx": LIST})

    dependents = sorted(get_dependents(tmp_path, "src.List.Row"), key=lambda d: d["source"])
    assert dependents == [_renders("src.List.List", "low"), _renders("src.List.Table")]
    partial = dict(
        conn.execute(
            "SELECT name, json_extract(metadata_json, '$.partial') FROM symbols"
            " WHERE kind = 'component'"
        )
    )
    assert partial == {"Row": None, "List": 1, "Table": None}


@pytest.mark.skipif(treesitter.missing("tsx") is not None, reason="tree-sitter is not installed")
def test_refresh_removes_a_deleted_same_file_usage(tmp_path):
    conn = _scan(tmp_path, {"src/Page.tsx": PAGE})
    (tmp_path / "src/Page.tsx").write_text(PAGE.replace("<Header />", ""))
    refresh_index(conn, tmp_path, load_config(tmp_path))

    assert get_dependents(tmp_path, "src.Page.Header") == []
    assert get_dependents(tmp_path, "src.Page.Card") == [_renders("src.Page.Page")]
