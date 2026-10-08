from pathlib import Path

import pytest

from project_mcp.plugins.registry import builtin_registry

ANALYZERS_ROOT = Path(__file__).resolve().parents[2] / "project_mcp" / "analyzers"


def test_no_analyzer_package_holds_a_plugins_code():
    # A plugin's code lives in project_mcp/plugins/<name>/; the analyzers
    # package keeps only language-neutral analysis.
    plugin_packages = set(builtin_registry().plugin_names()) | {"frameworks"}

    leftovers = sorted(
        str(path.relative_to(ANALYZERS_ROOT.parent))
        for name in plugin_packages
        for path in (ANALYZERS_ROOT / name).rglob("*.py")
    )

    assert leftovers == []


def test_the_guard_finds_plugin_code_in_a_nested_package(tmp_path, monkeypatch):
    nested = tmp_path / "analyzers" / "python" / "parsing"
    nested.mkdir(parents=True)
    (nested / "parser.py").write_text("")
    monkeypatch.setattr(
        "tests.integration.test_acceptance_plugin_code_in_plugin_packages.ANALYZERS_ROOT",
        tmp_path / "analyzers",
    )

    with pytest.raises(AssertionError, match="parsing/parser.py"):
        test_no_analyzer_package_holds_a_plugins_code()
