import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / ".agents/hooks/project-mcp-consult-gate.sh"
CONCURRENT_CHECKS = 16
ROUNDS = 10


def _mark(scratchpad):
    subprocess.run(
        ["bash", str(SCRIPT), "mark"],
        input=json.dumps({"tool_name": "mcp__project-mcp__find_symbol", "scratchpad_dir": str(scratchpad)}),
        capture_output=True,
        text=True,
        check=True,
    )


def _concurrent_checks(scratchpad):
    """Run the checks together and return (exit code, parsed output) for each."""
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
    return [(process.wait(), output) for process, output in zip(processes, outputs)]


def _is_denial(output):
    hook = output.get("hookSpecificOutput", {})
    return hook.get("hookEventName") == "PreToolUse" and hook.get("permissionDecision") == "deny"


def test_one_consult_allows_one_concurrent_gated_call_and_denies_the_rest(tmp_path):
    for round_number in range(ROUNDS):
        scratchpad = tmp_path / str(round_number)
        _mark(scratchpad)

        results = _concurrent_checks(scratchpad)

        assert [code for code, _ in results] == [0] * CONCURRENT_CHECKS
        allowed = [output for _, output in results if output == {}]
        others = [output for _, output in results if output != {}]
        assert len(allowed) == 1
        assert all(_is_denial(output) for output in others)
        assert list(scratchpad.iterdir()) == []
