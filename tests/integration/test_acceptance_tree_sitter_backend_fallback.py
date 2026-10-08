import sys

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import ensure_fresh_index, get_index_status, run_scan
from project_mcp.plugins import treesitter
from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.registry import PluginRegistry


class _ToyAnalyzer:
    """Parses with the rust grammar when it is installed, else with a regex."""

    def __init__(self):
        problem = treesitter.missing("rust")
        self.backend = "regex" if problem else "tree-sitter"
        self.warnings = [f"falls back to its regex parser: {problem}"] if problem else []

    def is_test_file(self, path):
        return False

    def analyze(self, path, source):
        return FileAnalysis(symbols=[])

    def resolve_import(self, importer, spec):
        return []


def _registry():
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="1.0.0",
            api_version=1,
            extensions={".toy": "toy"},
            analyzer=f"{__name__}:_ToyAnalyzer",
        )
    )
    return registry


def test_missing_grammar_falls_back_to_regex_and_the_scan_warns(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "tree_sitter_rust", None)
    (tmp_path / "main.toy").write_text("main\n")
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path), registry=_registry())

    warnings = get_index_status(conn).get("warnings", [])
    assert any(
        w.startswith("toy plugin falls back to its regex parser:") and "tree_sitter_rust" in w
        for w in warnings
    ), warnings


def test_switching_backend_reindexes_the_plugins_files(tmp_path, monkeypatch):
    (tmp_path / "main.toy").write_text("main\n")
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=_registry())
    before = conn.execute("SELECT parser_version FROM files WHERE path = 'main.toy'").fetchone()[0]

    monkeypatch.setitem(sys.modules, "tree_sitter_rust", None)
    ensure_fresh_index(conn, tmp_path, load_config(tmp_path), registry=_registry())
    after = conn.execute("SELECT parser_version FROM files WHERE path = 'main.toy'").fetchone()[0]

    assert before.startswith("toy@1.0.0#")
    assert after.startswith("toy@1.0.0#")
    assert after != before
