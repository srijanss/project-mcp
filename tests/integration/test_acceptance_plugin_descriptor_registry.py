from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.registry import builtin_registry


def test_scan_labels_files_with_the_language_of_a_registered_descriptor(tmp_path):
    (tmp_path / "main.go").write_text("package main\n")
    (tmp_path / "app.py").write_text("VALUE = 1\n")
    registry = builtin_registry()
    registry.register(
        PluginDescriptor(
            name="go", version="0.1.0", api_version=1, extensions={".go": "go"}
        )
    )
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path), registry=registry)

    assert dict(conn.execute("SELECT path, language FROM files")) == {
        "main.go": "go",
        "app.py": "python",
    }
