from pathlib import Path

HOOKS = Path(__file__).resolve().parents[2] / ".agents/hooks"


def test_only_the_consult_gate_script_remains_among_project_mcp_hooks():
    assert [path.name for path in HOOKS.glob("project-mcp-*")] == ["project-mcp-consult-gate.sh"]
