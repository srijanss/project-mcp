from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.registry import PluginRegistry


def test_scan_without_language_plugins_indexes_files_at_file_level(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    (tmp_path / ".project-mcp" / "config.toml").write_text("max_file_bytes = 200\n")
    (tmp_path / "app.py").write_text("def main():\n    return 1\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    (tmp_path / "README.md").write_text("# Demo\n")
    (tmp_path / "notes.xyz").write_text("plain notes\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")
    (tmp_path / "huge.txt").write_text("x" * 201)
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("export {}\n")
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path), registry=PluginRegistry())

    files = {
        path: (language, file_kind)
        for path, language, file_kind in conn.execute(
            "SELECT path, language, file_kind FROM files"
        )
    }
    assert files == {
        "app.py": (None, "source"),
        "pyproject.toml": ("toml", "config"),
        "README.md": ("markdown", "docs"),
        "notes.xyz": (None, "source"),
    }
    assert conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 0


def test_a_descriptor_can_label_its_files_as_config(tmp_path):
    from project_mcp.plugins.descriptor import PluginDescriptor

    (tmp_path / "main.hcl").write_text('variable "region" {}\n')
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="hcl",
            version="0.1.0",
            api_version=1,
            extensions={".hcl": "hcl"},
            file_kind="config",
        )
    )
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path), registry=registry)

    assert conn.execute("SELECT language, file_kind FROM files").fetchall() == [
        ("hcl", "config")
    ]
