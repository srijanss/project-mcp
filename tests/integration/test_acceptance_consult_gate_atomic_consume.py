import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / ".agents/hooks/project-mcp-consult-gate.sh"
CONCURRENT_CHECKS = 16
ROUNDS = 20


def _mark(scratchpad):
    subprocess.run(
        ["bash", str(SCRIPT), "mark"],
        input=json.dumps({"tool_name": "mcp__project-mcp__find_symbol", "scratchpad_dir": str(scratchpad)}),
        capture_output=True,
        text=True,
        check=True,
    )


def _concurrent_allows(scratchpad):
    payload = json.dumps(
        {"tool_name": "mcp__outside-in-tdd__init_feature", "scratchpad_dir": str(scratchpad)}
    )
    # Every process blocks reading stdin until it is closed, so closing them
    # back to back releases all the checks at (nearly) the same moment.
    processes = [
        subprocess.Popen(
            ["bash", str(SCRIPT), "check"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(CONCURRENT_CHECKS)
    ]
    for process in processes:
        process.stdin.write(payload)
    for process in processes:
        process.stdin.close()
    outputs = [json.loads(process.stdout.read()) for process in processes]
    for process in processes:
        process.wait()
    return sum(1 for output in outputs if output == {})


def test_one_consult_unlocks_only_one_of_many_concurrent_gated_calls(tmp_path):
    for round_number in range(ROUNDS):
        scratchpad = tmp_path / str(round_number)
        _mark(scratchpad)

        assert _concurrent_allows(scratchpad) == 1
