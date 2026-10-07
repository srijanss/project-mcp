import asyncio
import json

from project_mcp.main_stdio import build_server


def _coverage(server, tool, arguments):
    result = asyncio.run(server.call_tool(tool, arguments))
    assert result.is_error is False, result.content[0].text
    return json.loads(result.content[0].text)["coverage"]


def test_uncovered_languages_carry_a_note_naming_the_missing_plugin(tmp_path):
    (tmp_path / "app.py").write_text("def run():\n    pass\n")
    (tmp_path / "lib.rs").write_text("pub fn run() {}\n")
    (tmp_path / "main.go").write_text("package main\n")
    (tmp_path / "mcpctl.toml").write_text('[plugins]\ndisabled = ["rust"]\n')
    server = build_server(tmp_path)

    languages = _coverage(server, "get_project_overview", {})["languages"]

    assert languages["python"] == {"analyzed": True}
    assert languages["rust"]["reason"] == "plugin_disabled"
    assert "rust plugin is installed but disabled" in languages["rust"]["note"]
    assert "mcpctl.toml" in languages["rust"]["note"]
    assert languages["go"]["analyzed"] is False
    assert languages["go"]["reason"] == "plugin_not_installed"
    assert "No go plugin is installed" in languages["go"]["note"]
    assert "install" in languages["go"]["note"]
