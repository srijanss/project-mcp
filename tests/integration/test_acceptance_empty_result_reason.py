import asyncio
import json

from project_mcp.main_stdio import build_server


def _call(server, tool, arguments):
    result = asyncio.run(server.call_tool(tool, arguments))
    assert result.is_error is False, result.content[0].text
    return json.loads(result.content[0].text)


def test_empty_results_say_whether_anything_was_analyzed(tmp_path):
    rust_only = tmp_path / "rust_only"
    rust_only.mkdir()
    (rust_only / "lib.rs").write_text("pub fn run() {}\n")
    (rust_only / "mcpctl.toml").write_text('[plugins]\ndisabled = ["rust"]\n')
    python_only = tmp_path / "python_only"
    python_only.mkdir()
    (python_only / "app.py").write_text("def run():\n    pass\n")

    unanalyzed = _call(build_server(rust_only), "find_symbol", {"query": "run"})
    analyzed = _call(build_server(python_only), "find_symbol", {"query": "nothing"})
    git_only = _call(build_server(rust_only), "get_change_coupling", {"path": "lib.rs"})

    assert (unanalyzed["items"], unanalyzed["reason"]) == ([], "not_analyzed")
    assert (analyzed["items"], analyzed["reason"]) == ([], "none_found")
    assert (git_only["items"], git_only["reason"]) == ([], "none_found")


def test_test_relationships_of_an_unanalyzed_file_are_unknown_not_absent(tmp_path):
    (tmp_path / "lib.rs").write_text("pub fn run() {}\n")
    (tmp_path / "mcpctl.toml").write_text('[plugins]\ndisabled = ["rust"]\n')
    server = build_server(tmp_path)

    signals = _call(server, "get_legacy_signals", {"target": "lib.rs"})["items"]

    weak_tests = [s for s in signals if s["signal"] == "weak_test_relationship"]
    assert [s["confidence"] for s in weak_tests] == ["unknown"]
