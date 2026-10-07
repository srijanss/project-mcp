from project_mcp.plugins.descriptor import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="python",
    version="0.1.0",
    api_version=1,
    extensions={".py": "python"},
    analyzer="project_mcp.plugins.python.analyzer:PythonAnalyzer",
    manifests=("pyproject.toml", "setup.cfg", "setup.py", "requirements.txt"),
    ecosystem="python",
)
