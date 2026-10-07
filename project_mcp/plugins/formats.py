"""Config and docs formats every registry labels, with no plugin needed.

Data only: these label files and set their kind, and nothing analyzes them.
"""

from project_mcp.plugins.descriptor import PluginDescriptor

FORMAT_DESCRIPTORS = (
    PluginDescriptor(
        name="config-formats",
        version="0.1.0",
        api_version=1,
        extensions={
            ".toml": "toml",
            ".cfg": "ini",
            ".ini": "ini",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
        },
        file_kind="config",
    ),
    PluginDescriptor(
        name="docs-formats",
        version="0.1.0",
        api_version=1,
        extensions={".md": "markdown", ".rst": "restructuredtext"},
        file_kind="docs",
    ),
)
