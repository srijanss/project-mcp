from project_mcp.plugins.descriptor import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="javascript",
    version="0.1.0",
    api_version=1,
    extensions={
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
    },
)
