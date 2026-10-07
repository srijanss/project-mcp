import asyncio
import json

from project_mcp.main_stdio import build_server

PYTHON_ONLY = {"python": {"analyzed": True}}
RUST_DISABLED = {"analyzed": False, "reason": "plugin_disabled"}


def _call(server, tool, arguments):
    result = asyncio.run(server.call_tool(tool, arguments))
    assert result.is_error is False, result.content[0].text
    if result.structured_content is not None:
        return result.structured_content["result"]
    return json.loads(result.content[0].text)


def _without_notes(languages):
    return {
        language: {k: v for k, v in entry.items() if k != "note"}
        for language, entry in languages.items()
    }


def _project(tmp_path):
    (tmp_path / "app.py").write_text("def run():\n    pass\n")
    (tmp_path / "lib.rs").write_text("pub fn run() {}\n")
    (tmp_path / "mcpctl.toml").write_text('[plugins]\ndisabled = ["rust"]\n')
    return build_server(tmp_path)


def test_every_tool_response_carries_coverage_scoped_to_the_files_it_touches(tmp_path):
    server = _project(tmp_path)

    symbols = _call(server, "find_symbol", {"query": "run"})
    history = _call(server, "get_change_history", {"path": "lib.rs"})
    overview = _call(server, "get_project_overview", {})

    assert [s["qualified_name"] for s in symbols["items"]] == ["app.run"]
    assert symbols["coverage"] == {
        "status": "full",
        "active_plugins": ["python", "javascript", "django"],
        "languages": PYTHON_ONLY,
    }
    assert history["coverage"]["status"] == "none"
    assert _without_notes(history["coverage"]["languages"]) == {"rust": RUST_DISABLED}
    assert overview["coverage"]["status"] == "partial"
    assert _without_notes(overview["coverage"]["languages"]) == {
        **PYTHON_ONLY,
        "rust": RUST_DISABLED,
    }
