import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / ".claude/settings.json.example"


def _project_mcp_hooks(event, tool):
    """The project-mcp hook commands the example settings run for this tool."""
    entries = json.loads(SETTINGS.read_text())["hooks"].get(event, [])
    return [
        hook["command"]
        for entry in entries
        if re.fullmatch(entry["matcher"], tool)
        for hook in entry["hooks"]
        if "project-mcp-" in hook["command"]
    ]


def _fire(event, tool, scratchpad):
    """Run the hooks for one tool call; return the permission decisions."""
    decisions = []
    for command in _project_mcp_hooks(event, tool):
        completed = subprocess.run(
            ["bash", "-c", command],
            input=json.dumps({"tool_name": tool, "scratchpad_dir": str(scratchpad)}),
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)},
        )
        output = json.loads(completed.stdout)
        decisions.append(output.get("hookSpecificOutput", {}).get("permissionDecision"))
    return decisions


def test_only_init_feature_and_drill_down_need_a_fresh_project_mcp_consult(tmp_path):
    for tool in ("write_test", "write_test_skeleton", "write_code"):
        assert _fire("PreToolUse", f"mcp__outside-in-tdd__{tool}", tmp_path) == []

    for tool in ("init_feature", "drill_down"):
        assert _fire("PreToolUse", f"mcp__outside-in-tdd__{tool}", tmp_path) == ["deny"]

        _fire("PostToolUse", "mcp__project-mcp__find_symbol", tmp_path)
        assert _fire("PreToolUse", f"mcp__outside-in-tdd__{tool}", tmp_path) == [None]


def test_the_denial_names_the_project_mcp_tools_to_call_first(tmp_path):
    (command,) = _project_mcp_hooks("PreToolUse", "mcp__outside-in-tdd__init_feature")
    completed = subprocess.run(
        ["bash", "-c", command],
        input=json.dumps({"tool_name": "mcp__outside-in-tdd__init_feature", "scratchpad_dir": str(tmp_path)}),
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)},
    )

    reason = json.loads(completed.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    (marking,) = [
        entry["matcher"]
        for entry in json.loads(SETTINGS.read_text())["hooks"]["PostToolUse"]
        if any("project-mcp-consult-gate.sh\" mark" in hook["command"] for hook in entry["hooks"])
    ]
    for tool in marking.split("|"):
        assert tool.removeprefix("mcp__project-mcp__") in reason
