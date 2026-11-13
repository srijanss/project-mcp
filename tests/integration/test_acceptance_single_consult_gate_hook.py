import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ".agents/hooks/project-mcp-consult-gate.sh"


def _project_mcp_hook_scripts(settings_file):
    hooks = json.loads((ROOT / settings_file).read_text())["hooks"]
    return {
        match
        for entries in hooks.values()
        for entry in entries
        for hook in entry["hooks"]
        for match in re.findall(r"\.agents/hooks/project-mcp-[\w-]+\.sh", hook["command"])
    }


def test_the_consult_gate_is_the_only_project_mcp_hook_shipped():
    assert sorted(path.name for path in (ROOT / ".agents/hooks").glob("project-mcp-*")) == [
        "project-mcp-consult-gate.sh"
    ]

    for settings_file in (".claude/settings.json.example", ".claude/settings.json"):
        assert _project_mcp_hook_scripts(settings_file) == {GATE}

    scaffold = tomllib.loads((ROOT / "mcpctl.toml").read_text())["scaffold"]
    hook_copies = [entry for entry in scaffold["files"] if entry["from"].startswith(".agents/hooks/")]
    assert hook_copies == [{"from": GATE, "to": GATE}]
