import shutil
from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan

RUST_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "rust" / "sample_project"
)


def _copy_fixture(source_root: Path, tmp_path: Path) -> Path:
    project_root = tmp_path / source_root.name
    shutil.copytree(source_root, project_root)
    return project_root


def test_indexes_rust_crate_fixture(tmp_path):
    project_root = _copy_fixture(RUST_FIXTURE_ROOT, tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    rows = {
        row[0]: (row[1], row[2])
        for row in conn.execute(
            "SELECT qualified_name, kind, language FROM symbols"
        ).fetchall()
    }

    assert rows.get("src.lib.Widget") == ("struct", "rust")
    assert rows.get("src.lib.Describe") == ("trait", "rust")


def test_does_not_scan_target_dir_for_rust_project(tmp_path):
    project_root = _copy_fixture(RUST_FIXTURE_ROOT, tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    paths = {row[0] for row in conn.execute("SELECT path FROM files").fetchall()}

    assert not any(path.startswith("target/") for path in paths)
    assert "src/lib.rs" in paths


def test_indexes_rust_crate_fixture_cargo_dependency(tmp_path):
    project_root = _copy_fixture(RUST_FIXTURE_ROOT, tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    assert conn.execute(
        "SELECT name, ecosystem, declared_version, resolved_version FROM dependencies"
    ).fetchall() == [("serde", "rust", None, "1.0.197")]
