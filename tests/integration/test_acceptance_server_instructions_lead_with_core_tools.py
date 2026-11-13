import asyncio

from project_mcp.main_stdio import build_server

CORE_TOOLS = {
    "find_symbol": "locate",
    "get_symbol_context": "before drilling into",
    "get_tests_for": "existing tests",
    "get_dependents": "before changing",
}
SECONDARY_PREFIXES = ("get_change_", "get_hotspots", "get_architecture_", "get_legacy_", "get_context_for_")


def test_server_instructions_lead_with_the_core_tools_and_list_the_rest_in_one_line(tmp_path):
    server = build_server(tmp_path)
    lines = server.instructions.splitlines()
    tools = {tool.name for tool in asyncio.run(server.list_tools())}

    # The four core tools come first, in order, each saying when to use it.
    core = lines[1:5]
    assert [line.split(":")[0].strip("- `") for line in core] == list(CORE_TOOLS)
    for line, when in zip(core, CORE_TOOLS.values()):
        assert when in line

    # History, architecture, legacy and context tools appear only in one
    # "also available" line, which names every one the server registers.
    secondary = sorted(name for name in tools if name.startswith(SECONDARY_PREFIXES))
    assert len(secondary) == 12
    mentioning = [line for line in lines if any(name in line for name in secondary)]
    assert len(mentioning) == 1
    assert mentioning[0].startswith("Also available:")
    assert all(name in mentioning[0] for name in secondary)
