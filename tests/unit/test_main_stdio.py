import asyncio

import pytest
from mcp.server.mcpserver import MCPServer

from project_mcp.main_stdio import build_server, main
from project_mcp.config import ConfigError


def test_build_server_returns_mcp_server_for_valid_project_root(tmp_path):
    server = build_server(tmp_path)

    assert isinstance(server, MCPServer)


def test_build_server_registers_dependency_tools(tmp_path):
    server = build_server(tmp_path)

    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}

    assert {"list_dependencies", "get_dependency_version"} <= tool_names


def test_build_server_registers_project_and_symbol_tools(tmp_path):
    server = build_server(tmp_path)

    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}

    assert {
        "get_project_overview",
        "find_symbol",
        "get_symbol_context",
        "get_dependencies",
        "get_dependents",
    } <= tool_names


def test_get_project_overview_tool_call_returns_overview(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("class Widget:\n    pass\n")
    server = build_server(tmp_path)

    result = asyncio.run(server.call_tool("get_project_overview", {}))

    assert result.is_error is False
    assert "python" in result.content[0].text


def test_find_symbol_tool_call_returns_matches(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("class Widget:\n    pass\n")
    server = build_server(tmp_path)

    result = asyncio.run(server.call_tool("find_symbol", {"query": "widget"}))

    assert result.is_error is False
    assert "Widget" in result.content[0].text


def test_get_symbol_context_tool_call_returns_details(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("class Widget:\n    pass\n")
    server = build_server(tmp_path)

    result = asyncio.run(
        server.call_tool(
            "get_symbol_context", {"qualified_name": "app.models.Widget"}
        )
    )

    assert result.is_error is False
    assert "Widget" in result.content[0].text


def test_get_dependencies_tool_call_returns_relationships(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("VALUE = 1\n")
    (tmp_path / "app" / "importer.py").write_text("import app.models\n")
    server = build_server(tmp_path)

    result = asyncio.run(
        server.call_tool("get_dependencies", {"qualified_name": "app.importer"})
    )

    assert result.is_error is False
    assert "app/models.py" in result.content[0].text


def test_get_dependents_tool_call_returns_relationships(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("VALUE = 1\n")
    (tmp_path / "app" / "importer.py").write_text("import app.models\n")
    server = build_server(tmp_path)

    result = asyncio.run(
        server.call_tool("get_dependents", {"qualified_name": "app.models"})
    )

    assert result.is_error is False
    assert "app/importer.py" in result.content[0].text


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


def test_get_dependency_version_matches_name_case_and_separator_insensitively(
    tmp_path,
):
    (tmp_path / "requirements.txt").write_text("python-dotenv>=1.0\n")
    server = build_server(tmp_path)

    result = asyncio.run(
        server.call_tool("get_dependency_version", {"name": "Python_Dotenv"})
    )

    assert result.is_error is False
    assert "python-dotenv" in result.content[0].text


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
