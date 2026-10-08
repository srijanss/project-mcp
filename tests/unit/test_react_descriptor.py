from project_mcp.plugins.react.descriptor import DESCRIPTOR
from project_mcp.plugins.registry import BUILTIN_PLUGINS


def test_react_descriptor_is_a_framework_on_javascript():
    assert DESCRIPTOR.name == "react"
    assert DESCRIPTOR.kind == "framework"
    assert DESCRIPTOR.requires == ("javascript",)
    assert DESCRIPTOR.extensions == {}
    assert DESCRIPTOR.analyzer == "project_mcp.plugins.react.framework:ReactFramework"


def test_react_descriptor_is_a_builtin_plugin():
    assert "project_mcp.plugins.react.descriptor:DESCRIPTOR" in BUILTIN_PLUGINS
