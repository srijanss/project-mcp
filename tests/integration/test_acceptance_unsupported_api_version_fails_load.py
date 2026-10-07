from dataclasses import replace

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.registry import PluginRegistry
from project_mcp.plugins.rust.descriptor import DESCRIPTOR
from tests.golden import copy_fixture


def test_plugin_with_unsupported_api_version_is_disabled_and_reported(tmp_path):
    project_root = copy_fixture("rust", tmp_path)
    registry = PluginRegistry()
    registry.register(replace(DESCRIPTOR, api_version=99))
    conn = get_connection(project_root)

    run_scan(conn, project_root, load_config(project_root), registry=registry)

    assert conn.execute(
        "SELECT COUNT(*) FROM files WHERE language = 'rust'"
    ).fetchone()[0] > 0
    assert conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 0
    assert list(registry.failed_plugins) == ["rust"]
    assert "api_version 99" in registry.failed_plugins["rust"]
