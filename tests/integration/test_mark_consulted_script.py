import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / ".agents/hooks/project-mcp-mark-consulted.sh"


def test_mark_consulted_writes_only_the_session_marker(tmp_path):
    completed = subprocess.run(
        ["bash", str(SCRIPT)],
        input=json.dumps({"tool_name": "mcp__project-mcp__find_symbol", "scratchpad_dir": str(tmp_path)}),
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(completed.stdout) == {}
    assert [path.name for path in tmp_path.iterdir()] == [".project-mcp-session-consulted"]
