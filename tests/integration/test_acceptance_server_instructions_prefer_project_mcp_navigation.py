from project_mcp.main_stdio import build_server


def test_server_instructions_tell_the_agent_to_prefer_project_mcp_for_navigation(tmp_path):
    instructions = build_server(tmp_path).instructions

    navigation = [line for line in instructions.splitlines() if "grep" in line]

    assert len(navigation) == 1
    line = navigation[0]
    for tool in ("find_symbol", "get_symbol_context", "get_project_overview"):
        assert tool in line
    for shell_tool in ("grep", "find", "cat"):
        assert shell_tool in line
    assert "prefer" in line.lower()
