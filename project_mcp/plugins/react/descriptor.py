from project_mcp.plugins.descriptor import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="react",
    version="0.1.0",
    api_version=1,
    extensions={},
    kind="framework",
    requires=("javascript",),
    analyzer="project_mcp.plugins.react.framework:ReactFramework",
)
