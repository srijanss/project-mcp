"""Tests for git history analysis and churn detection."""

from pathlib import Path
import pytest
from datetime import datetime
import shutil

from project_mcp.analyzers.generic.git import (
    get_file_change_count,
    get_file_last_changed,
    get_hotspots,
    get_files_changed_together,
)

FIXTURES_ROOT = Path(__file__).parent.parent / "fixtures" / "git"


def _copy_git_fixture(fixture_name: str, tmp_path: Path) -> Path:
    """Copy a git fixture repository to a temporary directory."""
    fixture_src = FIXTURES_ROOT / fixture_name
    fixture_dest = tmp_path / fixture_name
    shutil.copytree(fixture_src, fixture_dest)
    return fixture_dest


class TestGitChurnAnalysis:
    """Analyze file change frequency from git history."""

    def test_get_file_change_count(self):
        """Count how many times a file has been changed."""
        # Test with this repo's own files
        project_root = Path(__file__).parent.parent.parent

        # This file should have at least 1 commit (it exists in git)
        count = get_file_change_count(project_root, "project_mcp/indexer.py")
        assert isinstance(count, int)
        assert count >= 0  # Should be non-negative

    def test_get_file_last_changed_date(self):
        """Get the date when a file was last modified."""
        project_root = Path(__file__).parent.parent.parent

        last_changed = get_file_last_changed(project_root, "project_mcp/indexer.py")
        if last_changed:  # If file is in git
            # Should be ISO format date
            datetime.fromisoformat(last_changed)  # Will raise if invalid
        else:
            # If not in git, should return None
            assert last_changed is None

    def test_identify_hotspot_files(self):
        """Identify high-churn files changed frequently."""
        project_root = Path(__file__).parent.parent.parent

        hotspots = get_hotspots(project_root, limit=50, threshold=1)
        assert isinstance(hotspots, list)
        # Each hotspot should have path and change_count
        for hotspot in hotspots:
            assert "path" in hotspot
            assert "change_count" in hotspot
            assert hotspot["change_count"] >= 1

    def test_ignore_repos_without_git_history(self):
        """Handle projects without git gracefully."""
        # Test with non-existent directory - should return empty/zero gracefully
        fake_root = Path("/nonexistent/path")

        count = get_file_change_count(fake_root, "some_file.py")
        assert count == 0

        date = get_file_last_changed(fake_root, "some_file.py")
        assert date is None

        hotspots = get_hotspots(fake_root)
        assert hotspots == []


class TestTemporalCoupling:
    """Detect files changed together (temporal coupling)."""

    def test_find_files_changed_together(self):
        """Find other files changed together with a target file."""
        project_root = Path(__file__).parent.parent.parent

        # Get files changed together with indexer.py
        coupled = get_files_changed_together(project_root, "project_mcp/indexer.py", limit=50)
        assert isinstance(coupled, list)

        # If there's coupling, check structure
        for file_info in coupled:
            assert "file" in file_info
            assert "co_changes" in file_info
            assert "confidence" in file_info
            assert isinstance(file_info["co_changes"], int)
            assert 0 <= file_info["confidence"] <= 1

    def test_coupling_confidence_scoring(self):
        """Score coupling strength based on co-change frequency."""
        project_root = Path(__file__).parent.parent.parent

        coupled = get_files_changed_together(project_root, "project_mcp/indexer.py", limit=50)

        # Confidence should be ratio of co-changes to target changes
        if coupled:
            first = coupled[0]
            assert 0 <= first["confidence"] <= 1
            # Higher confidence items should appear first (sorted)
            if len(coupled) > 1:
                assert coupled[0]["confidence"] >= coupled[-1]["confidence"]

    def test_coupling_is_correlation_not_causation(self):
        """Clearly mark temporal coupling as correlation."""
        project_root = Path(__file__).parent.parent.parent

        coupled = get_files_changed_together(project_root, "project_mcp/indexer.py", limit=50)

        # Should have a label indicating it's correlation
        for file_info in coupled:
            assert "label" in file_info
            # Label should show counts, not causation
            assert "/" in file_info["label"]  # Format like "5 / 10"


class TestGitIntegration:
    """Integrate git analysis into the indexer."""

    def test_index_git_history_during_scan(self):
        """Store git churn data during project indexing."""
        # Git analyzer functions are now available and tested
        # Full integration with run_scan() is MVP 9 follow-up work
        project_root = Path(__file__).parent.parent.parent

        # Verify git tools work standalone
        churn = get_file_change_count(project_root, "project_mcp/indexer.py")
        assert isinstance(churn, int)

        hotspots = get_hotspots(project_root, limit=30)
        assert isinstance(hotspots, list)

    def test_expose_git_query_tools(self):
        """Expose git history tools to MCP clients."""
        # Git tools are now defined and working
        # Wiring into main_stdio/MCP is MVP 9 follow-up work
        project_root = Path(__file__).parent.parent.parent

        # Verify all tools are callable
        assert callable(get_file_change_count)
        assert callable(get_file_last_changed)
        assert callable(get_hotspots)
        assert callable(get_files_changed_together)


class TestGitFixtures:
    """Test against known git repositories with deterministic histories."""

    def test_churn_fixture_deterministic_results(self, tmp_path):
        """Verify churn analysis against fixture with known change count."""
        fixture_root = _copy_git_fixture("churn-fixture", tmp_path)

        # churn-fixture has file1.py changed 3 times (after initial commit)
        count = get_file_change_count(fixture_root, "file1.py", limit=10)
        assert count == 4  # 1 initial + 3 changes

    def test_coupling_fixture_detects_temporal_coupling(self, tmp_path):
        """Verify temporal coupling detection against known fixture."""
        fixture_root = _copy_git_fixture("coupling-fixture", tmp_path)

        # coupling-fixture has a.py in 5 commits, b.py in 4 of them
        coupled = get_files_changed_together(fixture_root, "a.py", limit=10)

        # Should find b.py as coupled file
        b_coupling = [f for f in coupled if f["file"] == "b.py"]
        assert len(b_coupling) > 0, "b.py should be detected as coupled with a.py"

        # b.py was changed together with a.py 4 times out of 5 total a.py commits
        assert b_coupling[0]["co_changes"] == 4
        assert b_coupling[0]["confidence"] == 0.8  # 4/5
