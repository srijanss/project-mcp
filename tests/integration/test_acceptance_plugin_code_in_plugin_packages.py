from pathlib import Path

from project_mcp.plugins.registry import builtin_registry

ANALYZERS_ROOT = Path(__file__).resolve().parents[2] / "project_mcp" / "analyzers"


def test_no_analyzer_package_holds_a_plugins_code():
    # A plugin's code lives in project_mcp/plugins/<name>/; the analyzers
    # package keeps only language-neutral analysis.
    plugin_packages = set(builtin_registry().plugin_names()) | {"frameworks"}

    leftovers = sorted(
        str(path.relative_to(ANALYZERS_ROOT.parent))
        for name in plugin_packages
        for path in (ANALYZERS_ROOT / name).glob("*.py")
    )

    assert leftovers == []
