from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import get_index_status, run_scan
from project_mcp.plugins import registry as registry_module
from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.registry import configured_registry


class _EntryPoint:
    name = "python"
    value = "acme_python.descriptor:DESCRIPTOR"

    def load(self):
        return PluginDescriptor(
            name="python",
            version="9.9.9",
            api_version=1,
            extensions={".py": "python"},
            analyzer="acme_python.analyzer:AcmeAnalyzer",
        )


def test_an_installed_plugin_reusing_a_built_in_name_is_failed_and_the_scan_runs(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(registry_module, "entry_points", lambda group: [_EntryPoint()])
    (tmp_path / "app.py").write_text("def run():\n    pass\n")
    conn = get_connection(tmp_path)

    registry = configured_registry(load_config(tmp_path))
    run_scan(conn, tmp_path, load_config(tmp_path), registry=registry)

    assert "python" in registry.active_plugins()
    assert get_index_status(conn).get("warnings") == [
        "acme_python.descriptor:DESCRIPTOR plugin not registered:"
        " plugin name python is already registered"
    ]
    assert conn.execute(
        "SELECT COUNT(*) FROM symbols WHERE qualified_name = 'app.run'"
    ).fetchone()[0] == 1
