from pathlib import Path

import pytest

from project_mcp.config import ConfigError, load_config
from project_mcp.main_stdio import main
from project_mcp.plugins import registry as registry_module
from project_mcp.plugins.descriptor import PluginDescriptor

SNAKE = PluginDescriptor(
    name="snake",
    version="0.1.0",
    api_version=1,
    extensions={".py": "snake"},
    analyzer="project_mcp.plugins.python.analyzer:PythonAnalyzer",
)


@pytest.fixture
def snake_installed(monkeypatch):
    builtin = registry_module.builtin_registry

    def with_snake():
        registry = builtin()
        registry.register(SNAKE)
        return registry

    monkeypatch.setattr(registry_module, "builtin_registry", with_snake)


def test_two_enabled_plugins_claiming_an_extension_fail_startup(
    tmp_path, snake_installed, capsys, monkeypatch
):
    from mcp.server.mcpserver import MCPServer

    monkeypatch.setattr(MCPServer, "run", lambda self: None)

    exit_code = main([str(tmp_path)])

    assert exit_code != 0
    assert "plugins python and snake both claim .py" in capsys.readouterr().err


def test_disabling_one_of_the_claimants_resolves_the_conflict(tmp_path, snake_installed):
    (tmp_path / "mcpctl.toml").write_text('[plugins]\ndisabled = ["snake"]\n')

    registry = registry_module.configured_registry(load_config(tmp_path))

    assert registry.language_for(Path("app.py")) == "python"
    with pytest.raises(ConfigError, match="both claim .py"):
        (tmp_path / "mcpctl.toml").write_text("[plugins]\n")
        registry_module.configured_registry(load_config(tmp_path))
