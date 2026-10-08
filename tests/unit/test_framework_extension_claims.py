from pathlib import Path

from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.python.descriptor import DESCRIPTOR as python
from project_mcp.plugins.registry import PluginRegistry


class _ToyAnalyzer:
    pass


def _registry():
    registry = PluginRegistry()
    registry.register(python)
    registry.register(
        PluginDescriptor(
            name="toyframe",
            version="0.1.0",
            api_version=1,
            extensions={".toy": "toy"},
            kind="framework",
            requires=("python",),
            analyzer=f"{__name__}:_ToyAnalyzer",
        )
    )
    return registry


def test_a_framework_claiming_an_extension_analyzes_it_while_its_requirements_are_active():
    registry = _registry()

    assert registry.analyzed("toy")
    assert registry.fingerprint("toy").startswith("toyframe@0.1.0#")


def test_a_framework_claimed_language_is_unanalyzed_when_a_required_plugin_is_disabled():
    registry = _registry()
    registry.disable("python")

    assert registry.language_for(Path("page.toy")) == "toy"
    assert not registry.analyzed("toy")
    assert registry.analyzer_for("toy") is None
    assert registry.fingerprint("toy") is None
