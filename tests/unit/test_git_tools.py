"""Tests for the spec-named git history MCP tool wrappers."""

from pathlib import Path

from project_mcp.tools.git import get_change_coupling, get_change_history, get_hotspots
from tests.git_fixtures import build_git_fixture


def _copy_git_fixture(fixture_name: str, tmp_path: Path) -> Path:
    return build_git_fixture(fixture_name, tmp_path)


def test_get_change_history_returns_change_count_and_last_changed():
    project_root = Path(__file__).parent.parent.parent

    history = get_change_history(project_root, "project_mcp/indexer.py")

    assert isinstance(history["change_count"], int)
    assert history["change_count"] >= 0
    assert "last_changed" in history


def test_get_hotspots_returns_high_churn_files():
    project_root = Path(__file__).parent.parent.parent

    hotspots = get_hotspots(project_root)

    assert isinstance(hotspots, list)
    for hotspot in hotspots:
        assert "path" in hotspot
        assert "change_count" in hotspot


def test_get_change_coupling_returns_files_changed_together():
    project_root = Path(__file__).parent.parent.parent

    coupled = get_change_coupling(project_root, "project_mcp/indexer.py")

    assert isinstance(coupled, list)
    for file_info in coupled:
        assert "file" in file_info
        assert "co_changes" in file_info
        assert "confidence" in file_info


def test_get_change_history_uses_projects_configured_history_limit(tmp_path):
    fixture_root = _copy_git_fixture("churn-fixture", tmp_path)
    (fixture_root / ".project-mcp").mkdir()
    (fixture_root / ".project-mcp" / "config.toml").write_text(
        "git_history_limit = 2\n"
    )

    history = get_change_history(fixture_root, "file1.py")

    assert history["change_count"] == 2
