"""Tests for git history analysis and churn detection."""

from pathlib import Path
import pytest
from datetime import datetime

from project_mcp.analyzers.generic.git import (
    collect_git_file_stats,
    get_file_change_count,
    get_file_last_changed,
    get_hotspots,
    get_files_changed_together,
)
from project_mcp.config import ProjectConfig

from tests.git_fixtures import build_git_fixture


def _copy_git_fixture(fixture_name: str, tmp_path: Path) -> Path:
    """Build a git fixture repository in a temporary directory."""
    return build_git_fixture(fixture_name, tmp_path)


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

    def test_index_git_history_during_scan(self, tmp_path):
        """Store git churn data during project indexing."""
        from project_mcp.config import load_config
        from project_mcp.db import get_connection
        from project_mcp.indexer import run_scan

        fixture_root = _copy_git_fixture("churn-fixture", tmp_path)
        conn = get_connection(fixture_root)
        config = load_config(fixture_root)

        run_scan(conn, fixture_root, config)

        row = conn.execute(
            "SELECT gf.change_count, gf.last_changed FROM git_facts gf "
            "JOIN files f ON f.id = gf.file_id WHERE f.path = ?",
            ("file1.py",),
        ).fetchone()

        assert row is not None
        assert row[0] == 4  # 1 initial + 3 changes, per churn-fixture history
        datetime.fromisoformat(row[1])

    def test_expose_git_query_tools(self, tmp_path):
        """Expose git history tools to MCP clients."""
        import asyncio
        import json

        from project_mcp.main_stdio import build_server

        fixture_root = _copy_git_fixture("churn-fixture", tmp_path)
        server = build_server(fixture_root)

        history_result = asyncio.run(
            server.call_tool("get_change_history", {"path": "file1.py"})
        )
        hotspots_result = asyncio.run(server.call_tool("get_hotspots", {}))
        coupling_result = asyncio.run(
            server.call_tool("get_change_coupling", {"path": "file1.py"})
        )

        assert history_result.is_error is False
        history = json.loads(history_result.content[0].text)
        assert history["change_count"] == 4

        assert hotspots_result.is_error is False
        hotspots = hotspots_result.structured_content["result"]["items"]
        assert isinstance(hotspots, list)
        for hotspot in hotspots:
            assert {"path", "change_count", "last_changed"} <= hotspot.keys()

        assert coupling_result.is_error is False
        coupling = coupling_result.structured_content["result"]["items"]
        assert isinstance(coupling, list)


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


def _per_file_git_stats(project_root: Path, paths: list[str], limit: int) -> dict:
    return {
        path: {
            "change_count": get_file_change_count(project_root, path, limit=limit),
            "last_changed": get_file_last_changed(project_root, path),
            "coupled_file_count": len(
                get_files_changed_together(project_root, path, limit=limit)
            ),
        }
        for path in paths
    }


@pytest.mark.parametrize("limit", [2, 10])
@pytest.mark.parametrize("fixture_name", ["churn-fixture", "coupling-fixture"])
def test_collect_git_file_stats_matches_per_file_queries_on_fixtures(
    tmp_path, fixture_name, limit
):
    fixture_root = _copy_git_fixture(fixture_name, tmp_path)
    paths = ["file1.py", "a.py", "b.py", "missing.py"]

    stats = collect_git_file_stats(fixture_root, paths, limit=limit)

    assert stats == _per_file_git_stats(fixture_root, paths, limit)


def test_collect_git_file_stats_matches_per_file_queries_on_this_repo():
    import subprocess

    project_root = Path(__file__).parent.parent.parent
    tracked = subprocess.run(
        ["git", "ls-files", "project_mcp", "tests/unit"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    paths = [path for path in tracked if path.endswith(".py")][:25]

    stats = collect_git_file_stats(project_root, paths, limit=5)

    assert stats == _per_file_git_stats(project_root, paths, 5)


def test_collect_git_file_stats_uses_configured_limit(tmp_path):
    fixture_root = _copy_git_fixture("churn-fixture", tmp_path)
    config = ProjectConfig(project_root=fixture_root, git_history_limit=2)

    stats = collect_git_file_stats(fixture_root, ["file1.py"], config=config)

    assert stats["file1.py"]["change_count"] == 2


def test_collect_git_file_stats_without_git_history_reports_empty_facts():
    stats = collect_git_file_stats(Path("/nonexistent/path"), ["some_file.py"])

    assert stats == {
        "some_file.py": {
            "change_count": 0,
            "last_changed": None,
            "coupled_file_count": 0,
        }
    }


def test_get_file_change_count_respects_configured_commit_limit(tmp_path):
    fixture_root = _copy_git_fixture("churn-fixture", tmp_path)
    config = ProjectConfig(project_root=fixture_root, git_history_limit=2)

    count = get_file_change_count(fixture_root, "file1.py", config=config)

    assert count == 2


def test_get_hotspots_respects_configured_commit_limit(tmp_path):
    fixture_root = _copy_git_fixture("churn-fixture", tmp_path)
    config = ProjectConfig(project_root=fixture_root, git_history_limit=1)

    hotspots = get_hotspots(fixture_root, threshold=1, config=config)

    file1_hotspot = next((h for h in hotspots if h["path"] == "file1.py"), None)
    assert file1_hotspot is not None
    assert file1_hotspot["change_count"] == 1


def test_get_files_changed_together_respects_configured_commit_limit(tmp_path):
    fixture_root = _copy_git_fixture("coupling-fixture", tmp_path)
    config = ProjectConfig(project_root=fixture_root, git_history_limit=2)

    coupled = get_files_changed_together(fixture_root, "a.py", config=config)

    b_coupling = [f for f in coupled if f["file"] == "b.py"]
    assert len(b_coupling) > 0
    assert b_coupling[0]["co_changes"] <= 2


def test_tools_get_change_history_uses_projects_configured_history_limit(tmp_path):
    from project_mcp.tools.git import get_change_history as tool_get_change_history

    fixture_root = _copy_git_fixture("churn-fixture", tmp_path)
    (fixture_root / ".project-mcp").mkdir()
    (fixture_root / ".project-mcp" / "config.toml").write_text(
        "git_history_limit = 2\n"
    )

    history = tool_get_change_history(fixture_root, "file1.py")

    assert history["change_count"] == 2


def test_run_scan_persists_git_facts_using_configured_history_limit(tmp_path):
    from project_mcp.config import load_config
    from project_mcp.db import get_connection
    from project_mcp.indexer import run_scan

    fixture_root = _copy_git_fixture("churn-fixture", tmp_path)
    (fixture_root / ".project-mcp").mkdir()
    (fixture_root / ".project-mcp" / "config.toml").write_text(
        "git_history_limit = 2\n"
    )

    conn = get_connection(fixture_root)
    config = load_config(fixture_root)

    run_scan(conn, fixture_root, config)

    row = conn.execute(
        "SELECT gf.change_count FROM git_facts gf "
        "JOIN files f ON f.id = gf.file_id WHERE f.path = ?",
        ("file1.py",),
    ).fetchone()

    assert row is not None
    assert row[0] == 2
