import pytest

from project_mcp.plugins.javascript import analyzer as javascript_analyzer
from project_mcp.plugins.registry import builtin_registry


def _fingerprint(monkeypatch, problem):
    monkeypatch.setattr(javascript_analyzer.treesitter, "missing", lambda grammar: problem)
    return builtin_registry().fingerprint("astro")


def test_astro_fingerprint_changes_when_the_javascript_backend_does(monkeypatch):
    regex = _fingerprint(monkeypatch, "tree_sitter is not installed")
    tree_sitter = _fingerprint(monkeypatch, None)

    assert regex != tree_sitter


@pytest.mark.parametrize("problem, backend", [("missing", "regex"), (None, "tree-sitter")])
def test_astro_runs_on_the_backend_of_its_javascript_parser(monkeypatch, problem, backend):
    from project_mcp.plugins.astro.framework import AstroFramework

    monkeypatch.setattr(javascript_analyzer.treesitter, "missing", lambda grammar: problem)

    assert AstroFramework().backend == backend
