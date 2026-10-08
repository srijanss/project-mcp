from project_mcp.plugins.javascript import analyzer as javascript_analyzer
from project_mcp.plugins.registry import builtin_registry


def _warnings(monkeypatch, problem):
    monkeypatch.setattr(javascript_analyzer.treesitter, "missing", lambda grammar: problem)
    return builtin_registry().plugin_warnings()


def test_astro_reports_the_regex_fallback_of_its_javascript_parser(monkeypatch):
    warnings = _warnings(monkeypatch, "tree_sitter is not installed")

    assert warnings["astro"] == warnings["javascript"]
    assert warnings["astro"] == ["falls back to its regex parser: tree_sitter is not installed"]


def test_astro_reports_no_warnings_on_tree_sitter(monkeypatch):
    assert "astro" not in _warnings(monkeypatch, None)
