import pytest
from mcp.server.mcpserver import MCPServer

from main_stdio import build_server, main
from project_mcp.config import ConfigError


def test_build_server_returns_mcp_server_for_valid_project_root(tmp_path):
    server = build_server(tmp_path)

    assert isinstance(server, MCPServer)


def test_build_server_raises_clear_error_for_missing_project_root(tmp_path):
    missing_root = tmp_path / "does-not-exist"

    with pytest.raises(ConfigError, match="does not exist"):
        build_server(missing_root)


def test_main_prints_clear_error_and_returns_nonzero_for_missing_project_root(
    tmp_path, capsys
):
    missing_root = tmp_path / "does-not-exist"

    exit_code = main([str(missing_root)])

    assert exit_code == 1
    assert "does not exist" in capsys.readouterr().err


def test_main_falls_back_to_project_mcp_root_env_var_when_no_argv(
    tmp_path, capsys, monkeypatch
):
    missing_root = tmp_path / "does-not-exist"
    monkeypatch.setenv("PROJECT_MCP_ROOT", str(missing_root))

    exit_code = main([])

    assert exit_code == 1
    assert "does not exist" in capsys.readouterr().err
