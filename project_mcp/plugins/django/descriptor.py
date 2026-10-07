from project_mcp.plugins.descriptor import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="django",
    version="0.1.0",
    api_version=1,
    extensions={},
    kind="framework",
    requires=("python",),
    analyzer="project_mcp.plugins.django.framework:DjangoFramework",
)
