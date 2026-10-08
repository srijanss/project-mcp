from project_mcp.plugins.astro.descriptor import DESCRIPTOR
from project_mcp.plugins.registry import BUILTIN_PLUGINS


def test_astro_descriptor_is_a_framework_on_javascript():
    assert DESCRIPTOR.name == "astro"
    assert DESCRIPTOR.kind == "framework"
    assert DESCRIPTOR.requires == ("javascript",)
    assert DESCRIPTOR.extensions == {".astro": "astro"}
    assert DESCRIPTOR.analyzer == "project_mcp.plugins.astro.framework:AstroFramework"


def test_astro_descriptor_is_a_builtin_plugin():
    assert "project_mcp.plugins.astro.descriptor:DESCRIPTOR" in BUILTIN_PLUGINS
