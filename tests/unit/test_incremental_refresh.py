import shutil
import sqlite3
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


def _references_between(conn, source_name: str, target_name: str) -> list[tuple]:
    return conn.execute(
        """
        SELECT r.relationship_type, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND r.relationship_type = 'references'
          AND s.qualified_name = ? AND t.qualified_name = ?
        """,
        (source_name, target_name),
    ).fetchall()


def test_refresh_index_persists_references_for_edited_file(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    payment = project_root / "app" / "payment.py"
    payment.write_text(
        "class Payment:\n"
        "    status = 'new'\n"
        "\n"
        "    def run(self):\n"
        "        return 1\n"
    )
    run_scan(conn, project_root, config)
    assert _references_between(
        conn, "app.payment.Payment.run", "app.payment.Payment.status"
    ) == []

    time.sleep(0.01)
    payment.write_text(
        "class Payment:\n"
        "    status = 'new'\n"
        "\n"
        "    def run(self):\n"
        "        return self.status\n"
    )
    refresh_index(conn, project_root, config)

    assert _references_between(
        conn, "app.payment.Payment.run", "app.payment.Payment.status"
    ) == [("references", "high")]


def test_refresh_index_removes_stale_references_when_edit_drops_access(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    payment = project_root / "app" / "payment.py"
    payment.write_text(
        "class Payment:\n"
        "    status = 'new'\n"
        "\n"
        "    def run(self):\n"
        "        return self.status\n"
    )
    run_scan(conn, project_root, config)
    assert _references_between(
        conn, "app.payment.Payment.run", "app.payment.Payment.status"
    ) == [("references", "high")]

    time.sleep(0.01)
    payment.write_text(
        "class Payment:\n"
        "    status = 'new'\n"
        "\n"
        "    def run(self):\n"
        "        return 1\n"
    )
    refresh_index(conn, project_root, config)

    assert _references_between(
        conn, "app.payment.Payment.run", "app.payment.Payment.status"
    ) == []


def _calls_between(conn, source_name: str, target_name: str) -> list[tuple]:
    return conn.execute(
        """
        SELECT r.relationship_type, r.confidence FROM relationships r
        JOIN symbols s ON s.id = r.source_entity_id
        JOIN symbols t ON t.id = r.target_entity_id
        WHERE r.source_entity_type = 'symbol' AND r.target_entity_type = 'symbol'
          AND r.relationship_type = 'calls'
          AND s.qualified_name = ? AND t.qualified_name = ?
        """,
        (source_name, target_name),
    ).fetchall()


def _write_cross_module_project(project_root: Path, service_body: str = "helper()") -> None:
    (project_root / "app" / "helpers.py").write_text(
        "def helper():\n"
        "    return 1\n"
    )
    (project_root / "app" / "service.py").write_text(
        "from app.helpers import helper\n"
        "\n"
        "\n"
        "def run():\n"
        f"    return {service_body}\n"
    )


def test_refresh_index_persists_cross_module_calls_for_edited_caller(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    _write_cross_module_project(project_root, service_body="1")
    run_scan(conn, project_root, config)
    assert _calls_between(conn, "app.service.run", "app.helpers.helper") == []

    time.sleep(0.01)
    _write_cross_module_project(project_root, service_body="helper()")
    refresh_index(conn, project_root, config)

    assert _calls_between(conn, "app.service.run", "app.helpers.helper") == [
        ("calls", "high")
    ]


def test_refresh_index_keeps_cross_module_calls_when_callee_file_is_edited(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    _write_cross_module_project(project_root)
    run_scan(conn, project_root, config)
    assert _calls_between(conn, "app.service.run", "app.helpers.helper") == [
        ("calls", "high")
    ]

    time.sleep(0.01)
    (project_root / "app" / "helpers.py").write_text(
        "def helper():\n"
        "    return 2\n"
    )
    refresh_index(conn, project_root, config)

    assert _calls_between(conn, "app.service.run", "app.helpers.helper") == [
        ("calls", "high")
    ]


def test_refresh_index_does_not_duplicate_cross_module_calls_to_unchanged_files(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "helpers.py").write_text("def helper():\n    return 1\n")
    (project_root / "app" / "other.py").write_text("def other():\n    return 1\n")
    (project_root / "app" / "service.py").write_text(
        "from app.helpers import helper\n"
        "from app.other import other\n"
        "\n"
        "\n"
        "def run():\n"
        "    other()\n"
        "    return helper()\n"
    )
    run_scan(conn, project_root, config)

    time.sleep(0.01)
    (project_root / "app" / "helpers.py").write_text("def helper():\n    return 2\n")
    refresh_index(conn, project_root, config)

    assert _calls_between(conn, "app.service.run", "app.other.other") == [
        ("calls", "high")
    ]
    assert _calls_between(conn, "app.service.run", "app.helpers.helper") == [
        ("calls", "high")
    ]


def test_refresh_index_removes_cross_module_call_when_edit_drops_it(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    _write_cross_module_project(project_root, service_body="helper()")
    run_scan(conn, project_root, config)
    assert _calls_between(conn, "app.service.run", "app.helpers.helper") == [
        ("calls", "high")
    ]

    time.sleep(0.01)
    _write_cross_module_project(project_root, service_body="1")
    refresh_index(conn, project_root, config)

    assert _calls_between(conn, "app.service.run", "app.helpers.helper") == []


FIELD = "app.payments.Payment.gateway_captured_card_number"


def _write_cross_file_attribute_project(project_root: Path, access: str = "payment.gateway_captured_card_number") -> None:
    (project_root / "app" / "payments.py").write_text(
        "class Payment:\n"
        "    gateway_captured_card_number = None\n"
    )
    (project_root / "app" / "receipts.py").write_text(
        "from app.payments import Payment\n"
        "\n"
        "\n"
        "def show(payment):\n"
        f"    return {access}\n"
    )


def test_refresh_index_persists_cross_file_attribute_reference_for_edited_accessor(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    _write_cross_file_attribute_project(project_root, access="1")
    run_scan(conn, project_root, config)
    assert _references_between(conn, "app.receipts.show", FIELD) == []

    time.sleep(0.01)
    _write_cross_file_attribute_project(project_root)
    refresh_index(conn, project_root, config)

    assert _references_between(conn, "app.receipts.show", FIELD) == [
        ("references", "low")
    ]


def test_refresh_index_keeps_cross_file_attribute_reference_when_field_file_is_edited(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    _write_cross_file_attribute_project(project_root)
    run_scan(conn, project_root, config)
    assert _references_between(conn, "app.receipts.show", FIELD) == [
        ("references", "low")
    ]

    time.sleep(0.01)
    (project_root / "app" / "payments.py").write_text(
        "class Payment:\n"
        "    gateway_captured_card_number = 'x'\n"
    )
    refresh_index(conn, project_root, config)

    assert _references_between(conn, "app.receipts.show", FIELD) == [
        ("references", "low")
    ]


def test_refresh_index_does_not_duplicate_cross_file_attribute_references(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "payments.py").write_text(
        "class Payment:\n    gateway_captured_card_number = None\n"
    )
    (project_root / "app" / "orders.py").write_text(
        "class Order:\n    total_price = None\n"
    )
    (project_root / "app" / "receipts.py").write_text(
        "from app.payments import Payment\n"
        "from app.orders import Order\n"
        "\n"
        "\n"
        "def show(thing):\n"
        "    return (thing.gateway_captured_card_number, thing.total_price)\n"
    )
    run_scan(conn, project_root, config)

    time.sleep(0.01)
    (project_root / "app" / "payments.py").write_text(
        "class Payment:\n    gateway_captured_card_number = 'x'\n"
    )
    refresh_index(conn, project_root, config)

    assert _references_between(conn, "app.receipts.show", FIELD) == [
        ("references", "low")
    ]
    assert _references_between(
        conn, "app.receipts.show", "app.orders.Order.total_price"
    ) == [("references", "low")]


def test_refresh_index_keeps_constant_references_when_constant_file_is_edited(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)
    (project_root / "app" / "settings.py").write_text("MAX_RETRIES = 3\n")
    (project_root / "app" / "limits.py").write_text("TIMEOUT = 5\n")
    (project_root / "app" / "worker.py").write_text(
        "from app.settings import MAX_RETRIES\n"
        "from app.limits import TIMEOUT\n"
        "\n"
        "\n"
        "def run():\n"
        "    return MAX_RETRIES, TIMEOUT\n"
    )
    run_scan(conn, project_root, config)

    time.sleep(0.01)
    (project_root / "app" / "settings.py").write_text("MAX_RETRIES = 4\n")
    refresh_index(conn, project_root, config)

    assert _references_between(
        conn, "app.worker.run", "app.settings.MAX_RETRIES"
    ) == [("references", "high")]
    assert _references_between(conn, "app.worker.run", "app.limits.TIMEOUT") == [
        ("references", "high")
    ]


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


class _CommitCountingConnection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.commit_count = 0

    def commit(self):
        self.commit_count += 1
        return super().commit()


def test_refresh_index_commits_once_for_multiple_changed_files(tmp_path):
    """Refreshing several changed files should batch into a single commit,
    not one commit per file."""
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)
    db_path = project_root / ".project-mcp" / "index.db"
    conn.close()

    time.sleep(0.01)
    models_file = project_root / "app" / "models.py"
    models_file.write_text(models_file.read_text() + "\n\nclass AnotherModel:\n    pass\n")
    init_file = project_root / "app" / "__init__.py"
    init_file.write_text(init_file.read_text() + "\n# touched\n")

    counting_conn = sqlite3.connect(db_path, factory=_CommitCountingConnection)
    refresh_index(counting_conn, project_root, config)

    assert counting_conn.commit_count == 1, (
        f"refresh_index committed {counting_conn.commit_count} times for 2 changed "
        "files, expected a single batched commit"
    )
