from dataclasses import replace

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.python.descriptor import DESCRIPTOR
from project_mcp.plugins.registry import PluginRegistry
from tests.golden import copy_fixture


def test_python_files_are_analyzed_only_through_the_python_plugin(tmp_path):
    project_root = copy_fixture("python", tmp_path)
    registry = PluginRegistry()
    registry.register(replace(DESCRIPTOR, analyzer=None))
    conn = get_connection(project_root)

    run_scan(conn, project_root, load_config(project_root), registry=registry)

    assert dict(
        conn.execute("SELECT path, file_kind FROM files WHERE language = 'python'")
    ) == {
        "app/__init__.py": "source",
        "app/models.py": "source",
        "tests/test_models.py": "source",
    }
    assert conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM tests").fetchone()[0] == 0
