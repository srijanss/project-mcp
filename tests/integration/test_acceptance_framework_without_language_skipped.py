from project_mcp.config import load_config
from project_mcp.plugins.registry import configured_registry
from project_mcp.tools.project import get_project_overview


def test_a_framework_whose_language_plugin_is_disabled_is_skipped_with_a_warning(tmp_path):
    (tmp_path / "manage.py").write_text("import django\n")
    (tmp_path / "mcpctl.toml").write_text('[plugins]\ndisabled = ["python"]\n')

    overview = get_project_overview(tmp_path)

    assert overview["index_status"].get("warnings") == [
        "django plugin skipped: it requires the python plugin, which is not active"
    ]
    assert configured_registry(load_config(tmp_path)).frameworks() == []
