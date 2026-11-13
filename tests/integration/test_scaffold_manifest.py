import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _scaffold_files():
    return tomllib.loads((ROOT / "mcpctl.toml").read_text())["scaffold"]["files"]


def test_scaffold_copies_only_the_consult_gate_hook():
    hooks = [entry for entry in _scaffold_files() if entry["from"].startswith(".agents/hooks/")]

    assert hooks == [
        {"from": ".agents/hooks/project-mcp-consult-gate.sh", "to": ".agents/hooks/project-mcp-consult-gate.sh"}
    ]
