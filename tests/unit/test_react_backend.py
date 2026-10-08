import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins import treesitter
from project_mcp.plugins.react import tree_usages, usages
from project_mcp.plugins.react.framework import ReactFramework

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    "src/Item.tsx": "export function Item() {\n  return <li />;\n}\n",
    "src/App.tsx": (
        "import { Item } from './Item';\n\n"
        "export function App() {\n  return <Item />;\n}\n"
    ),
}


def _scan(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    return conn.execute(
        "SELECT COUNT(*) FROM relationships WHERE relationship_type = 'renders'"
    ).fetchone()[0]


def _forbid(monkeypatch, module, *names):
    def fail(*args, **kwargs):
        raise AssertionError("the other backend's parser was used")

    for name in names:
        monkeypatch.setattr(module, name, fail)


@pytest.mark.skipif(treesitter.missing("tsx") is not None, reason="tree-sitter is not installed")
def test_with_tree_sitter_available_the_syntax_tree_reads_imports_and_tags(tmp_path, monkeypatch):
    _forbid(monkeypatch, usages, "imported_names", "jsx_tags")

    assert ReactFramework().backend == "tree-sitter"
    assert ReactFramework().warnings == []
    assert _scan(tmp_path) == 1


def test_without_tree_sitter_the_regex_parser_reads_imports_and_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(treesitter, "missing", lambda grammar: "forced off")
    _forbid(monkeypatch, tree_usages, "imported_names", "jsx_tags")

    assert ReactFramework().backend == "regex"
    assert ReactFramework().warnings == ["falls back to its regex parser: forced off"]
    assert _scan(tmp_path) == 1
