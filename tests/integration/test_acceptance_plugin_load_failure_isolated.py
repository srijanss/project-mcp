from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import get_index_status, run_scan
from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.registry import builtin_registry


class _BrokenAnalyzer:
    def __init__(self):
        raise RuntimeError("missing toolchain")


def test_a_plugin_that_fails_to_load_is_disabled_and_the_scan_continues(tmp_path):
    registry = builtin_registry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.1.0",
            api_version=1,
            extensions={".toy": "toy"},
            analyzer=f"{__name__}:_BrokenAnalyzer",
        )
    )
    (tmp_path / "app.py").write_text("def run():\n    pass\n")
    (tmp_path / "main.toy").write_text("main\n")
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path), registry=registry)

    assert registry.failed_plugins == {"toy": "failed to load: missing toolchain"}
    assert get_index_status(conn).get("warnings") == [
        "toy plugin failed to load: missing toolchain"
    ]
    assert conn.execute(
        "SELECT language FROM files WHERE path = 'main.toy'"
    ).fetchone()[0] == "toy"
    assert conn.execute(
        "SELECT COUNT(*) FROM symbols WHERE qualified_name = 'app.run'"
    ).fetchone()[0] == 1
