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


def _denied(output):
    return output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def test_a_consult_unlocks_exactly_one_gated_call(tmp_path):
    scratchpad = tmp_path / "scratchpad"
    gated = {"tool_name": "mcp__outside-in-tdd__init_feature", "scratchpad_dir": str(scratchpad)}

    assert _denied(_hook("check", gated))

    _hook("mark", {"tool_name": "mcp__project-mcp__find_symbol", "scratchpad_dir": str(scratchpad)})
    assert not _denied(_hook("check", gated))
    assert _denied(_hook("check", gated))

    assert not _denied(_hook("check", {"tool_name": "mcp__outside-in-tdd__drill_down"}))
