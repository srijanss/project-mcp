import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / ".agents/hooks/project-mcp-consult-gate.sh"


def _hook(mode, payload):
    completed = subprocess.run(
        ["bash", str(SCRIPT), mode],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _decision(output):
    return output.get("hookSpecificOutput", {}).get("permissionDecision")


def test_check_denies_a_gated_call_when_project_mcp_was_not_consulted(tmp_path):
    output = _hook(
        "check",
        {"tool_name": "mcp__outside-in-tdd__init_feature", "scratchpad_dir": str(tmp_path)},
    )

    assert _decision(output) == "deny"
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "mcp__outside-in-tdd__init_feature" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_check_allows_once_after_a_consult_and_consumes_the_marker(tmp_path):
    gated = {"tool_name": "mcp__outside-in-tdd__drill_down", "scratchpad_dir": str(tmp_path)}

    assert _hook("mark", {"tool_name": "mcp__project-mcp__find_symbol", "scratchpad_dir": str(tmp_path)}) == {}

    assert _hook("check", gated) == {}
    assert _decision(_hook("check", gated)) == "deny"


def test_both_modes_fail_open_without_a_scratchpad_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert _hook("mark", {"tool_name": "mcp__project-mcp__find_symbol"}) == {}
    assert _hook("check", {"tool_name": "mcp__outside-in-tdd__init_feature"}) == {}
    assert list(tmp_path.iterdir()) == []
