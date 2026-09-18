import asyncio

import pytest
from mcp.server.mcpserver import MCPServer

from main_stdio import build_server, main
from project_mcp.config import ConfigError


def test_build_server_returns_mcp_server_for_valid_project_root(tmp_path):
    server = build_server(tmp_path)

    assert isinstance(server, MCPServer)


def test_build_server_registers_dependency_tools(tmp_path):
    server = build_server(tmp_path)

    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}

    assert {"list_dependencies", "get_dependency_version"} <= tool_names


def test_dependency_tools_describe_their_inputs(tmp_path):
    server = build_server(tmp_path)

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    assert "ecosystem" in tools["list_dependencies"].input_schema["properties"]
    assert {"name", "ecosystem"} <= tools["get_dependency_version"].input_schema[
        "properties"
    ].keys()


def test_dependency_tools_call_against_the_project_root(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests>=2.31\n")
    server = build_server(tmp_path)

    result = asyncio.run(server.call_tool("list_dependencies", {}))

    assert result.is_error is False
    assert "requests" in result.content[0].text


def test_dependency_tools_read_the_persisted_index(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests>=2.31\n")
    server = build_server(tmp_path)
    asyncio.run(server.call_tool("list_dependencies", {}))
    (tmp_path / "requirements.txt").write_text("rich>=13\n")

    result = asyncio.run(server.call_tool("list_dependencies", {}))

    assert "requests" in result.content[0].text
    assert "rich" not in result.content[0].text


def test_get_dependency_version_reads_the_persisted_index(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests>=2.31\n")
    server = build_server(tmp_path)
    asyncio.run(server.call_tool("list_dependencies", {}))
    (tmp_path / "requirements.txt").write_text("rich>=13\n")

    result = asyncio.run(
        server.call_tool("get_dependency_version", {"name": "requests"})
    )

    assert "requests" in result.content[0].text


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
