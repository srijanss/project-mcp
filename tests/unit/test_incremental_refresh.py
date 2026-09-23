import shutil
import time
from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import (
    begin_index,
    get_index_status,
    mark_index_complete,
    refresh_index,
    run_scan,
)

FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "python" / "sample_project"
)


def _copy_fixture(tmp_path: Path) -> Path:
    project_root = tmp_path / "sample_project"
    shutil.copytree(FIXTURE_ROOT, project_root)
    return project_root


def test_refresh_index_detects_edited_file_and_re_indexes(tmp_path):
    """Edited file should be re-indexed with updated content."""
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)
    initial_status = get_index_status(conn)
    assert initial_status["status"] == "fresh"

    # Simulate file edit: sleep to ensure mtime changes, then modify
    time.sleep(0.01)
    app_file = project_root / "app" / "models.py"
    original = app_file.read_text()
    app_file.write_text(original + "\n\nclass NewModel:\n    pass\n")

    # refresh should detect the change
    refresh_index(conn, project_root, config)

    # New symbol should exist in index
    new_symbol = conn.execute(
        "SELECT name FROM symbols WHERE name = 'NewModel'"
    ).fetchone()
    assert new_symbol is not None


def test_refresh_index_detects_deleted_file(tmp_path):
    """Deleted file should be removed from index and relationships cleaned up."""
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)
    initial_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    assert initial_files > 0

    # Delete a file
    test_file = project_root / "tests" / "test_models.py"
    test_file.unlink()

    # refresh should detect the deletion
    refresh_index(conn, project_root, config)

    # File should be gone from index
    deleted = conn.execute(
        "SELECT id FROM files WHERE path = 'tests/test_models.py'"
    ).fetchone()
    assert deleted is None

    # Final file count should be less
    final_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    assert final_files < initial_files


def test_refresh_index_skips_unchanged_files(tmp_path):
    """Unchanged files should not be reparsed during refresh."""
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    # Record initial parse times for all files
    initial_times = {
        row[0]: row[1]
        for row in conn.execute("SELECT path, indexed_at FROM files").fetchall()
    }
    assert len(initial_times) > 0

    # Sleep and refresh without changing files
    time.sleep(0.01)
    refresh_index(conn, project_root, config)

    # Check that indexed_at times haven't changed for unchanged files
    final_times = {
        row[0]: row[1]
        for row in conn.execute("SELECT path, indexed_at FROM files").fetchall()
    }

    # Most files should have unchanged indexed_at (within reasonable tolerance)
    unchanged_count = sum(
        1 for path in initial_times
        if initial_times.get(path) == final_times.get(path)
    )
    assert unchanged_count > 0, "Some files should remain unchanged"


def test_get_index_status_returns_stale_when_files_changed(tmp_path):
    """get_index_status should detect when filesystem has changes."""
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)
    assert get_index_status(conn, project_root, config)["status"] == "fresh"

    # Modify a file
    time.sleep(0.01)
    app_file = project_root / "app" / "models.py"
    app_file.write_text(app_file.read_text() + "\n# comment\n")

    # Status should detect stale state
    status = get_index_status(conn, project_root, config)
    assert status["status"] == "stale"


def test_get_index_status_returns_stale_when_file_deleted(tmp_path):
    """get_index_status should detect when indexed file is deleted from disk."""
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)
    assert get_index_status(conn, project_root, config)["status"] == "fresh"

    # Delete a file
    test_file = project_root / "tests" / "test_models.py"
    test_file.unlink()

    # Status should detect stale state
    status = get_index_status(conn, project_root, config)
    assert status["status"] == "stale"


def test_get_index_status_includes_last_refresh_time(tmp_path):
    """Status should include last_refresh_time for cache validation."""
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)
    status = get_index_status(conn)

    assert "last_refresh_time" in status
    assert status["last_refresh_time"] is not None


def test_refresh_index_after_edit_returns_fresh_status(tmp_path):
    """After refresh, status should return to fresh."""
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)
    assert get_index_status(conn, project_root, config)["status"] == "fresh"

    # Modify a file
    time.sleep(0.01)
    app_file = project_root / "app" / "models.py"
    app_file.write_text(app_file.read_text() + "\n# comment\n")
    assert get_index_status(conn, project_root, config)["status"] == "stale"

    # Refresh should bring it back to fresh
    refresh_index(conn, project_root, config)
    assert get_index_status(conn, project_root, config)["status"] == "fresh"


def test_refresh_index_preserves_relationships_for_unchanged_symbols(tmp_path):
    """Refresh should preserve existing relationships for unchanged code."""
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)
    initial_rel_count = conn.execute(
        "SELECT COUNT(*) FROM relationships"
    ).fetchone()[0]
    assert initial_rel_count > 0

    # Add a new file without modifying existing ones
    time.sleep(0.01)
    new_file = project_root / "app" / "new_module.py"
    new_file.write_text("# new module\ndef new_function():\n    pass\n")

    refresh_index(conn, project_root, config)

    # Existing relationships should still be there
    final_rel_count = conn.execute(
        "SELECT COUNT(*) FROM relationships"
    ).fetchone()[0]
    assert final_rel_count >= initial_rel_count


def test_refresh_index_detects_new_file(tmp_path):
    """New files should be indexed during refresh."""
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)
    initial_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]

    # Add a new Python file
    time.sleep(0.01)
    new_file = project_root / "app" / "utils.py"
    new_file.write_text("def helper():\n    pass\n")

    refresh_index(conn, project_root, config)

    # File should be in index
    added = conn.execute(
        "SELECT id FROM files WHERE path = 'app/utils.py'"
    ).fetchone()
    assert added is not None

    final_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    assert final_files > initial_files


def test_refresh_index_cleans_relationships_on_delete(tmp_path):
    """Deleting a file should clean all its relationships."""
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)
    initial_rel_count = conn.execute(
        "SELECT COUNT(*) FROM relationships"
    ).fetchone()[0]

    # Delete a file
    app_file = project_root / "app" / "models.py"
    app_file.unlink()

    refresh_index(conn, project_root, config)

    # Relationships involving deleted file should be gone
    final_rel_count = conn.execute(
        "SELECT COUNT(*) FROM relationships"
    ).fetchone()[0]
    # Some relationships may have been removed if they involved the deleted file
    assert final_rel_count <= initial_rel_count

    # No relationships should reference the deleted file
    orphan_rels = conn.execute(
        """
        SELECT COUNT(*) FROM relationships
        WHERE source_entity_type = 'file'
              AND source_entity_id NOT IN (SELECT id FROM files)
           OR target_entity_type = 'file'
              AND target_entity_id NOT IN (SELECT id FROM files)
        """
    ).fetchone()[0]
    assert orphan_rels == 0


def test_refresh_index_skips_git_facts_for_unchanged_files(tmp_path, monkeypatch):
    """Unchanged files should not trigger new git-log subprocess calls during refresh."""
    import subprocess

    project_root = _copy_fixture(tmp_path)
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
    subprocess.run(["git", "add", "."], cwd=project_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )

    config = load_config(project_root)
    conn = get_connection(project_root)
    run_scan(conn, project_root, config)

    import project_mcp.indexer as indexer_module

    recomputed_paths = []
    original_get_file_change_count = indexer_module.get_file_change_count

    def tracking_get_file_change_count(project_root_arg, path, **kwargs):
        recomputed_paths.append(path)
        return original_get_file_change_count(project_root_arg, path, **kwargs)

    monkeypatch.setattr(
        indexer_module, "get_file_change_count", tracking_get_file_change_count
    )

    time.sleep(0.01)
    refresh_index(conn, project_root, config)

    assert recomputed_paths == [], (
        "refresh_index recomputed git facts for unchanged files: "
        f"{recomputed_paths}"
    )
