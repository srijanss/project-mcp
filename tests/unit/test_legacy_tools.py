"""Tests for the spec-named legacy signal MCP tool wrappers."""

import subprocess

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import ensure_fresh_index
from project_mcp.tools.legacy import get_legacy_hotspots, get_legacy_signals


def _init_git_repo(project_root):
    subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )


def test_get_legacy_signals_returns_signals_for_a_known_hotspot(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "big.py").write_text("x = 1\ny = 2\nz = 3\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_big.py").write_text(
        "from app.big import x\n\n\ndef test_big():\n    assert x\n"
    )
    (tmp_path / ".project-mcp").mkdir()
    (tmp_path / ".project-mcp" / "config.toml").write_text("large_file_lines = 1\n")

    signals = get_legacy_signals(tmp_path, "app/big.py")

    assert len(signals) == 1
    assert signals[0]["signal"] == "large_file"
    assert signals[0]["severity"] == "medium"
    assert signals[0]["confidence"] == "high"
    assert signals[0]["evidence"]
    assert "target" not in signals[0]


def test_get_legacy_signals_returns_empty_list_for_clean_target(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "small.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_small.py").write_text(
        "from app.small import x\n\n\ndef test_small():\n    assert x\n"
    )

    signals = get_legacy_signals(tmp_path, "app/small.py")

    assert signals == []


def test_get_legacy_hotspots_ranks_targets_by_signal_count(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "big.py").write_text("x = 1\ny = 2\nz = 3\n")
    (tmp_path / "app" / "small.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_big.py").write_text(
        "from app.big import x\n\n\ndef test_big():\n    assert x\n"
    )
    (tmp_path / "tests" / "test_small.py").write_text(
        "from app.small import x\n\n\ndef test_small():\n    assert x\n"
    )
    (tmp_path / ".project-mcp").mkdir()
    (tmp_path / ".project-mcp" / "config.toml").write_text(
        'large_file_lines = 1\nlegacy_paths = ["app/big.py"]\n'
    )

    hotspots = get_legacy_hotspots(tmp_path)

    assert hotspots[0]["target"] == "app/big.py"
    assert hotspots[0]["signal_count"] == 2
    assert len(hotspots[0]["signals"]) == 2
    assert all("this code is bad" not in str(s).lower() for s in hotspots[0]["signals"])
    assert all("must refactor" not in str(s).lower() for s in hotspots[0]["signals"])


def test_get_legacy_hotspots_respects_limit(tmp_path):
    (tmp_path / "app").mkdir()
    for i in range(3):
        (tmp_path / "app" / f"big{i}.py").write_text("x = 1\ny = 2\nz = 3\n")
    (tmp_path / ".project-mcp").mkdir()
    (tmp_path / ".project-mcp" / "config.toml").write_text("large_file_lines = 1\n")

    hotspots = get_legacy_hotspots(tmp_path, limit=2)

    assert len(hotspots) == 2


def test_get_legacy_hotspots_surfaces_real_fixture_hotspot_with_combined_signals(tmp_path):
    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "hotspot.py").write_text("x = 1\ny = 2\nz = 3\n")
    (project_root / ".project-mcp").mkdir()
    (project_root / ".project-mcp" / "config.toml").write_text(
        "large_file_lines = 1\nhigh_churn_count = 2\n"
    )

    _init_git_repo(project_root)
    for i in range(4):
        (project_root / "app" / "hotspot.py").write_text(f"x = {i}\ny = 2\nz = 3\n")
        subprocess.run(["git", "add", "."], cwd=project_root, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"change {i}"],
            cwd=project_root,
            check=True,
            capture_output=True,
        )

    hotspots = get_legacy_hotspots(project_root)

    hotspot = next(h for h in hotspots if h["target"] == "app/hotspot.py")
    signal_names = {s["signal"] for s in hotspot["signals"]}
    assert {"large_file", "high_churn", "weak_test_relationship"} <= signal_names
    for signal in hotspot["signals"]:
        assert signal["evidence"]
        assert "this code is bad" not in str(signal).lower()
        assert "must refactor" not in str(signal).lower()

    signals = get_legacy_signals(project_root, "app/hotspot.py")
    assert {s["signal"] for s in signals} == signal_names


def test_get_legacy_hotspots_returns_empty_for_a_clean_project(tmp_path):
    project_root = tmp_path / "clean"
    (project_root / "app").mkdir(parents=True)
    (project_root / "app" / "small.py").write_text("x = 1\n")
    (project_root / "tests").mkdir()
    (project_root / "tests" / "test_small.py").write_text(
        "from app.small import x\n\n\ndef test_small():\n    assert x\n"
    )

    hotspots = get_legacy_hotspots(project_root)

    assert hotspots == []
    assert get_legacy_signals(project_root, "app/small.py") == []


def _insert_malformed_signal_row(project_root, target):
    config = load_config(project_root)
    conn = get_connection(project_root)
    ensure_fresh_index(conn, project_root, config)
    conn.execute(
        "INSERT INTO legacy_signals (target, signal, severity, confidence, evidence)"
        " VALUES (?, 'large_file', 'medium', 'high', ?)",
        (target, "{not valid json"),
    )
    conn.commit()


def test_get_legacy_signals_falls_back_to_empty_evidence_on_malformed_json(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "big.py").write_text("x = 1\n")
    _insert_malformed_signal_row(tmp_path, "app/big.py")

    signals = get_legacy_signals(tmp_path, "app/big.py")

    large_file_signal = next(s for s in signals if s["signal"] == "large_file")
    assert large_file_signal["evidence"] == []


def test_get_legacy_hotspots_falls_back_to_empty_evidence_on_malformed_json(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "big.py").write_text("x = 1\n")
    _insert_malformed_signal_row(tmp_path, "app/big.py")

    hotspots = get_legacy_hotspots(tmp_path)

    hotspot = next(h for h in hotspots if h["target"] == "app/big.py")
    large_file_signal = next(s for s in hotspot["signals"] if s["signal"] == "large_file")
    assert large_file_signal["evidence"] == []
