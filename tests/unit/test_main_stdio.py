import asyncio
import json

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


def test_get_symbol_context_tool_returns_source_callers_callees_and_tests(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "flow.py").write_text(
        "def leaf():\n    return 1\n\n\n"
        "def middle():\n    return leaf()\n\n\n"
        "def top():\n    return middle()\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_flow.py").write_text(
        "from app.flow import middle\n\n\ndef test_middle():\n    assert middle()\n"
    )
    server = build_server(tmp_path)

    result = asyncio.run(
        server.call_tool("get_symbol_context", {"qualified_name": "app.flow.middle"})
    )

    details = json.loads(result.content[0].text)
    assert details["source"] == "def middle():\n    return leaf()"
    assert [c["symbol"] for c in details["callers"]] == ["app.flow.top"]
    assert [c["symbol"] for c in details["callees"]] == ["app.flow.leaf"]
    assert details["tests"][0]["test_file"] == "tests/test_flow.py"


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


def test_build_server_registers_test_relationship_tools(tmp_path):
    server = build_server(tmp_path)

    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}

    assert {"get_tests_for", "get_test_summary"} <= tool_names


def test_get_tests_for_tool_advertises_a_limit_argument(tmp_path):
    server = build_server(tmp_path)

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    limit = tools["get_tests_for"].input_schema["properties"]["limit"]
    assert limit["type"] == "integer"
    assert limit["default"] == 5


def test_get_tests_for_tool_call_returns_relationships(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("VALUE = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_models.py").write_text(
        "from app.models import VALUE\n\n\ndef test_value():\n    assert VALUE\n"
    )
    server = build_server(tmp_path)

    result = asyncio.run(
        server.call_tool("get_tests_for", {"qualified_name": "app.models"})
    )

    assert result.is_error is False
    assert "tests/test_models.py" in result.content[0].text


def test_get_tests_for_tool_call_with_limit_zero_names_every_test(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text(
        "class Box:\n    def value(self):\n        return 1\n"
    )
    (tmp_path / "tests").mkdir()
    many = "".join(
        f"def test_value_{i:02d}():\n    assert Box().value()\n\n\n" for i in range(7)
    )
    (tmp_path / "tests" / "test_models.py").write_text(
        "from app.models import Box\n\n\n" + many
    )
    server = build_server(tmp_path)

    result = asyncio.run(
        server.call_tool(
            "get_tests_for", {"qualified_name": "app.models.Box.value", "limit": 0}
        )
    )

    assert result.is_error is False
    text = result.content[0].text
    assert all(f"tests.test_models.test_value_{i:02d}" in text for i in range(7))


def test_get_test_summary_tool_call_returns_totals(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("VALUE = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_models.py").write_text(
        "from app.models import VALUE\n\n\ndef test_value():\n    assert VALUE\n"
    )
    server = build_server(tmp_path)

    result = asyncio.run(server.call_tool("get_test_summary", {}))

    assert result.is_error is False
    assert "total_tests" in result.content[0].text


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


def test_dependency_tools_read_the_persisted_index_when_unchanged(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests>=2.31\n")
    server = build_server(tmp_path)
    asyncio.run(server.call_tool("list_dependencies", {}))

    result = asyncio.run(server.call_tool("list_dependencies", {}))

    assert "requests" in result.content[0].text


def test_dependency_tools_pick_up_edits_made_since_last_call(tmp_path):
    """MVP 13: a tool call must not silently serve stale data."""
    import time

    (tmp_path / "requirements.txt").write_text("requests>=2.31\n")
    server = build_server(tmp_path)
    asyncio.run(server.call_tool("list_dependencies", {}))

    time.sleep(0.01)
    (tmp_path / "requirements.txt").write_text("rich>=13\n")

    result = asyncio.run(server.call_tool("list_dependencies", {}))

    assert "rich" in result.content[0].text
    assert "requests" not in result.content[0].text


def test_get_dependency_version_reads_the_persisted_index(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests>=2.31\n")
    server = build_server(tmp_path)
    asyncio.run(server.call_tool("list_dependencies", {}))

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


def test_build_server_registers_index_status_and_refresh_tools(tmp_path):
    server = build_server(tmp_path)

    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}

    assert {"get_index_status", "refresh_index"} <= tool_names


def test_get_index_status_tool_reports_never_indexed_before_any_call(tmp_path):
    server = build_server(tmp_path)

    result = asyncio.run(server.call_tool("get_index_status", {}))

    assert result.is_error is False
    assert "never_indexed" in result.content[0].text


def test_get_index_status_tool_detects_stale_after_edit(tmp_path):
    import time

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("class Widget:\n    pass\n")
    server = build_server(tmp_path)
    asyncio.run(server.call_tool("get_project_overview", {}))

    time.sleep(0.01)
    (tmp_path / "app" / "models.py").write_text(
        "class Widget:\n    pass\n\nclass Gadget:\n    pass\n"
    )

    result = asyncio.run(server.call_tool("get_index_status", {}))

    assert result.is_error is False
    assert "stale" in result.content[0].text


def test_refresh_index_tool_reindexes_changed_files_and_returns_fresh(tmp_path):
    import time

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("class Widget:\n    pass\n")
    server = build_server(tmp_path)
    asyncio.run(server.call_tool("get_project_overview", {}))

    time.sleep(0.01)
    (tmp_path / "app" / "models.py").write_text(
        "class Widget:\n    pass\n\nclass Gadget:\n    pass\n"
    )

    result = asyncio.run(server.call_tool("refresh_index", {}))
    assert result.is_error is False
    assert "fresh" in result.content[0].text

    found = asyncio.run(server.call_tool("find_symbol", {"query": "Gadget"}))
    assert "Gadget" in found.content[0].text


def test_build_server_registers_git_tools(tmp_path):
    server = build_server(tmp_path)

    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}

    assert {"get_change_history", "get_hotspots", "get_change_coupling"} <= tool_names


def test_build_server_registers_architecture_tools(tmp_path):
    server = build_server(tmp_path)

    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}

    assert {"get_architecture_facts", "get_architecture_context"} <= tool_names


def test_build_server_registers_legacy_tools(tmp_path):
    server = build_server(tmp_path)

    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}

    assert {"get_legacy_hotspots", "get_legacy_signals"} <= tool_names


def test_build_server_registers_context_pack_tools(tmp_path):
    server = build_server(tmp_path)

    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}

    assert {
        "get_context_for_symbol",
        "get_context_for_feature",
        "get_context_for_bug",
        "get_context_for_refactor",
        "get_context_for_architecture",
    } <= tool_names


def test_get_context_for_symbol_tool_call_returns_context(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("VALUE = 1\n")
    server = build_server(tmp_path)

    result = asyncio.run(
        server.call_tool("get_context_for_symbol", {"qualified_name": "app.models"})
    )

    assert result.is_error is False
    assert "app.models" in result.content[0].text


def test_tool_failure_reports_the_underlying_error_message(tmp_path, monkeypatch):
    """A crash must not reach the client as a bare "Error executing tool"."""
    import sqlite3

    from mcp.server.mcpserver.exceptions import ToolError

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("project_mcp.main_stdio.find_symbol", locked)
    server = build_server(tmp_path)

    with pytest.raises(ToolError, match="OperationalError: database is locked"):
        asyncio.run(server.call_tool("find_symbol", {"query": "x"}))


def test_oversized_list_result_is_truncated_and_says_so(tmp_path, monkeypatch):
    """Huge results overflow the client's token limit and get saved to a file."""
    import json

    from project_mcp.main_stdio import MAX_TOOL_OUTPUT_CHARS

    rows = [{"name": f"symbol_{i}", "file": "app/models.py"} for i in range(5000)]
    monkeypatch.setattr("project_mcp.main_stdio.get_dependents", lambda *a, **k: rows)
    server = build_server(tmp_path)

    result = asyncio.run(
        server.call_tool("get_dependents", {"qualified_name": "app.models"})
    )

    payload = result.structured_content["result"]
    assert payload["truncated"] is True
    assert payload["total"] == 5000
    assert payload["returned"] == len(payload["items"]) < 5000
    assert len(json.dumps(payload["items"])) <= MAX_TOOL_OUTPUT_CHARS


def test_truncated_list_result_fits_the_cap_including_its_wrapper(tmp_path, monkeypatch):
    import json

    from project_mcp.main_stdio import MAX_TOOL_OUTPUT_CHARS

    rows = [{"n": "x" * 37} for _ in range(5000)]  # ~48 chars each, wrapper ~70
    monkeypatch.setattr("project_mcp.main_stdio.get_dependents", lambda *a, **k: rows)
    server = build_server(tmp_path)

    result = asyncio.run(
        server.call_tool("get_dependents", {"qualified_name": "app.models"})
    )

    payload = result.structured_content["result"]
    assert len(json.dumps(payload)) <= MAX_TOOL_OUTPUT_CHARS


def test_oversized_dict_result_trims_its_longest_list_and_says_so(tmp_path, monkeypatch):
    import json

    from project_mcp.main_stdio import MAX_TOOL_OUTPUT_CHARS

    pack = {
        "target": "app.models",
        "dependents": [{"source": f"app.mod_{i}"} for i in range(5000)],
        "related_tests": [{"test": "tests/test_models.py"}],
    }
    monkeypatch.setattr(
        "project_mcp.main_stdio.get_context_for_symbol", lambda *a, **k: pack
    )
    server = build_server(tmp_path)

    result = asyncio.run(
        server.call_tool("get_context_for_symbol", {"qualified_name": "app.models"})
    )

    payload = json.loads(result.content[0].text)
    assert len(json.dumps(payload)) <= MAX_TOOL_OUTPUT_CHARS
    assert payload["truncated"] is True
    assert payload["truncated_fields"]["dependents"]["total"] == 5000
    assert payload["truncated_fields"]["dependents"]["returned"] == len(
        payload["dependents"]
    )
    assert payload["related_tests"] == [{"test": "tests/test_models.py"}]
    assert payload["target"] == "app.models"


def test_oversized_dict_without_lists_trims_its_longest_string_and_says_so(
    tmp_path, monkeypatch
):
    import json

    from project_mcp.main_stdio import MAX_TOOL_OUTPUT_CHARS

    pack = {"target": "app.models", "source": "x" * 50_000}
    monkeypatch.setattr(
        "project_mcp.main_stdio.get_context_for_symbol", lambda *a, **k: pack
    )
    server = build_server(tmp_path)

    result = asyncio.run(
        server.call_tool("get_context_for_symbol", {"qualified_name": "app.models"})
    )

    payload = json.loads(result.content[0].text)
    assert len(json.dumps(payload)) <= MAX_TOOL_OUTPUT_CHARS
    assert payload["truncated"] is True
    assert payload["truncated_fields"]["source"]["total"] == 50_000
    assert payload["truncated_fields"]["source"]["returned"] == len(payload["source"])
    assert payload["target"] == "app.models"


def test_find_symbol_tool_pages_results_and_says_where_to_continue(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "widgets.py").write_text(
        "".join(f"class Widget{i}:\n    pass\n\n\n" for i in range(5))
    )
    server = build_server(tmp_path)

    first = asyncio.run(
        server.call_tool("find_symbol", {"query": "widget", "kind": "class", "limit": 2})
    ).structured_content["result"]
    last = asyncio.run(
        server.call_tool(
            "find_symbol", {"query": "widget", "kind": "class", "limit": 2, "offset": 4}
        )
    ).structured_content["result"]

    assert first["truncated"] is True
    assert first["returned"] == len(first["items"]) == 2
    assert first["next_offset"] == 2
    assert [row["name"] for row in last["items"]] == ["Widget4"]


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"limit": 0}, "limit must be at least 1"),
        ({"limit": -3}, "limit must be at least 1"),
        ({"offset": -1}, "offset must not be negative"),
    ],
)
def test_find_symbol_tool_rejects_invalid_paging_arguments(
    tmp_path, arguments, message
):
    from mcp.server.mcpserver.exceptions import ToolError

    server = build_server(tmp_path)

    with pytest.raises(ToolError, match=message):
        asyncio.run(server.call_tool("find_symbol", {"query": "x", **arguments}))


def test_small_list_result_is_returned_unchanged(tmp_path, monkeypatch):
    rows = [{"name": "symbol_1", "file": "app/models.py"}]
    monkeypatch.setattr("project_mcp.main_stdio.get_dependents", lambda *a, **k: rows)
    server = build_server(tmp_path)

    result = asyncio.run(
        server.call_tool("get_dependents", {"qualified_name": "app.models"})
    )

    assert result.structured_content["result"]["items"] == rows


def test_find_symbol_tool_call_sees_edits_made_after_first_index(tmp_path):
    """A tool call must not silently serve stale data (MVP 13)."""
    import time

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("class Widget:\n    pass\n")
    server = build_server(tmp_path)
    asyncio.run(server.call_tool("find_symbol", {"query": "Widget"}))

    time.sleep(0.01)
    (tmp_path / "app" / "models.py").write_text(
        "class Widget:\n    pass\n\nclass Gadget:\n    pass\n"
    )

    result = asyncio.run(server.call_tool("find_symbol", {"query": "Gadget"}))

    assert result.is_error is False
    assert "Gadget" in result.content[0].text


@pytest.mark.parametrize("alias", ["query", "symbol"])
@pytest.mark.parametrize(
    "tool", ["get_symbol_context", "get_dependents", "get_tests_for", "get_dependencies"]
)
def test_symbol_tools_accept_query_and_symbol_as_aliases_for_qualified_name(
    tmp_path, tool, alias
):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("VALUE = 1\n")
    (tmp_path / "app" / "importer.py").write_text("import app.models\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_models.py").write_text(
        "from app.models import VALUE\n\n\ndef test_value():\n    assert VALUE\n"
    )
    server = build_server(tmp_path)

    target = "app.importer" if tool == "get_dependencies" else "app.models"

    by_name = asyncio.run(server.call_tool(tool, {"qualified_name": target}))
    by_alias = asyncio.run(server.call_tool(tool, {alias: target}))

    assert by_name.content, "fixture should give every tool something to return"
    assert by_alias.is_error is False
    assert [c.text for c in by_alias.content] == [c.text for c in by_name.content]


def test_symbol_tools_say_which_argument_is_missing(tmp_path):
    from mcp.server.mcpserver.exceptions import ToolError

    server = build_server(tmp_path)

    with pytest.raises(ToolError, match="qualified_name is required"):
        asyncio.run(server.call_tool("get_dependents", {}))


def test_dict_results_are_serialized_compactly(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text("class Widget:\n    pass\n")
    server = build_server(tmp_path)

    result = asyncio.run(
        server.call_tool("get_symbol_context", {"qualified_name": "app.models.Widget"})
    )

    text = result.content[0].text
    assert result.is_error is False
    assert len(result.content) == 1
    assert "\n  " not in text
    assert json.loads(text)["symbol"]["qualified_name"] == "app.models.Widget"


def test_list_dependencies_filters_indexed_dependencies_by_any_ecosystem(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests>=2.31\n")
    (tmp_path / "Cargo.toml").write_text('[dependencies]\nserde = "1"\n')
    server = build_server(tmp_path)

    result = asyncio.run(server.call_tool("list_dependencies", {"ecosystem": "rust"}))

    assert result.structured_content["result"]["items"] == [
        {"name": "serde", "ecosystem": "rust", "version": "1", "version_status": "declared"}
    ]


def test_get_dependency_version_matches_non_python_names_exactly(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"lodash.merge": "^4.6.2"}}\n')
    server = build_server(tmp_path)

    loose = asyncio.run(server.call_tool("get_dependency_version", {"name": "Lodash-Merge"}))
    exact = asyncio.run(server.call_tool("get_dependency_version", {"name": "lodash.merge"}))

    assert json.loads(loose.content[0].text)["status"] == "not_found"
    assert json.loads(exact.content[0].text)["ecosystem"] == "npm"


def test_build_server_rejects_an_invalid_plugin_selection_at_startup(tmp_path, monkeypatch):
    from project_mcp.plugins import registry as registry_module

    def conflicting(config):
        raise ConfigError("plugins python and snake both claim .py")

    monkeypatch.setattr(registry_module, "configured_registry", conflicting)

    with pytest.raises(ConfigError, match="both claim .py"):
        build_server(tmp_path)


def test_tool_responses_carry_a_coverage_block_and_lists_move_under_items(tmp_path):
    (tmp_path / "app.py").write_text("class Widget:\n    pass\n")
    server = build_server(tmp_path)

    found = asyncio.run(server.call_tool("find_symbol", {"query": "Widget"}))
    overview = asyncio.run(server.call_tool("get_project_overview", {}))

    symbols = found.structured_content["result"]
    assert [s["qualified_name"] for s in symbols["items"]] == ["app.Widget"]
    assert symbols["coverage"]["languages"] == {"python": {"analyzed": True}}
    assert json.loads(overview.content[0].text)["coverage"]["status"] == "full"


def test_empty_results_of_plugin_backed_tools_say_when_nothing_was_analyzed(tmp_path):
    (tmp_path / "lib.rs").write_text("pub fn run() {}\n")
    (tmp_path / "mcpctl.toml").write_text('[plugins]\ndisabled = ["rust"]\n')
    server = build_server(tmp_path)

    symbols = asyncio.run(server.call_tool("find_symbol", {"query": "run"}))
    hotspots = asyncio.run(server.call_tool("get_hotspots", {}))

    assert json.loads(symbols.content[0].text)["reason"] == "not_analyzed"
    assert json.loads(hotspots.content[0].text)["reason"] == "none_found"


@pytest.mark.parametrize("tool", ["get_index_status", "refresh_index"])
def test_index_status_tools_report_the_servers_plugins(tmp_path, tool):
    (tmp_path / "mcpctl.toml").write_text('[plugins]\ndisabled = ["rust"]\n')
    server = build_server(tmp_path)

    result = asyncio.run(server.call_tool(tool, {}))

    plugins = json.loads(result.content[0].text)["plugins"]
    assert plugins["active"] == ["python", "javascript", "django"]
