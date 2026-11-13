import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("settings_file", [".claude/settings.json.example", ".claude/settings.json"])
def test_only_one_post_tool_use_hook_writes_the_consumable_consult_marker(settings_file, tmp_path):
    # Claude Code runs matching hooks in parallel: if two of them wrote the
    # marker, a gated call could consume it between the writes and leave a
    # second unlock behind for one consult.
    entries = json.loads((ROOT / settings_file).read_text())["hooks"]["PostToolUse"]
    commands = [
        hook["command"]
        for entry in entries
        if "mcp__project-mcp__find_symbol" in entry["matcher"].split("|")
        for hook in entry["hooks"]
    ]

    writers = []
    for index, command in enumerate(commands):
        scratchpad = tmp_path / str(index)
        subprocess.run(
            ["bash", "-c", command],
            input=json.dumps({"tool_name": "mcp__project-mcp__find_symbol", "scratchpad_dir": str(scratchpad)}),
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)},
        )
        if (scratchpad / ".project-mcp-consulted").exists():
            writers.append(command)

    assert writers == ['"$CLAUDE_PROJECT_DIR/.agents/hooks/project-mcp-consult-gate.sh" mark']
