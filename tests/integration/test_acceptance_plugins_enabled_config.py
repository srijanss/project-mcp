import pytest

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import ensure_fresh_index
from project_mcp.plugins.registry import configured_registry


@pytest.mark.parametrize(
    "plugins_section",
    ['disabled = ["rust"]', 'enabled = ["python", "javascript", "django"]'],
)
def test_a_plugin_left_out_by_mcpctl_toml_labels_but_does_not_analyze(
    tmp_path, plugins_section
):
    (tmp_path / "app.py").write_text("def run():\n    pass\n")
    (tmp_path / "lib.rs").write_text("pub fn run() {}\n")
    (tmp_path / "mcpctl.toml").write_text(f"[plugins]\n{plugins_section}\n")
    config = load_config(tmp_path)
    conn = get_connection(tmp_path)

    ensure_fresh_index(conn, tmp_path, config)

    assert dict(conn.execute("SELECT path, language FROM files WHERE language IN ('python', 'rust')")) == {
        "app.py": "python",
        "lib.rs": "rust",
    }
    assert {
        row[0]
        for row in conn.execute(
            "SELECT f.path FROM symbols s JOIN files f ON f.id = s.file_id"
        )
    } == {"app.py"}
    registry = configured_registry(config)
    assert (registry.analyzed("python"), registry.analyzed("rust")) == (True, False)


def test_all_builtin_plugins_analyze_when_mcpctl_toml_has_no_plugins_section(tmp_path):
    (tmp_path / "mcpctl.toml").write_text('name = "demo"\n')

    registry = configured_registry(load_config(tmp_path))

    assert all(
        registry.analyzed(language) for language in ("python", "javascript", "typescript", "rust")
    )
