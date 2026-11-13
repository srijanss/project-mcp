import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILES = [".claude/settings.json.example", ".claude/settings.json"]
GATE = '"$CLAUDE_PROJECT_DIR/.agents/hooks/project-mcp-consult-gate.sh"'
QUERY_TOOLS = (
    "mcp__project-mcp__find_symbol|mcp__project-mcp__get_symbol_context"
    "|mcp__project-mcp__get_dependencies|mcp__project-mcp__get_dependents"
    "|mcp__project-mcp__get_project_overview"
)


def _matchers_running(settings_file, event, command):
    hooks = json.loads((ROOT / settings_file).read_text())["hooks"].get(event, [])
    return [entry["matcher"] for entry in hooks if any(h["command"] == command for h in entry["hooks"])]


@pytest.mark.parametrize("settings_file", SETTINGS_FILES)
def test_consult_gate_checks_only_init_feature_and_drill_down(settings_file):
    assert _matchers_running(settings_file, "PreToolUse", f"{GATE} check") == [
        "mcp__outside-in-tdd__init_feature|mcp__outside-in-tdd__drill_down"
    ]
    assert _matchers_running(settings_file, "PostToolUse", f"{GATE} mark") == [QUERY_TOOLS]


@pytest.mark.parametrize("settings_file", SETTINGS_FILES)
def test_no_session_gate_or_old_consult_hooks_are_wired(settings_file):
    commands = [
        hook["command"]
        for entries in json.loads((ROOT / settings_file).read_text())["hooks"].values()
        for entry in entries
        for hook in entry["hooks"]
    ]

    for retired in ("project-mcp-session-gate.sh", "project-mcp-reminder.sh", "project-mcp-mark-consulted.sh"):
        assert not [command for command in commands if retired in command]
