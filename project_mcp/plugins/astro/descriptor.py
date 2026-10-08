from project_mcp.plugins.descriptor import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="astro",
    version="0.1.0",
    api_version=1,
    extensions={".astro": "astro"},
    kind="framework",
    requires=("javascript",),
    analyzer="project_mcp.plugins.astro.framework:AstroFramework",
)
