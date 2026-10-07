from project_mcp.plugins.descriptor import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="rust", version="0.1.0", api_version=1, extensions={".rs": "rust"}
)
