import shutil
from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan

JS_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "javascript" / "sample_project"
)
REACT_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "react" / "sample_project"
)


def _copy_fixture(source_root: Path, tmp_path: Path) -> Path:
    project_root = tmp_path / source_root.name
    shutil.copytree(source_root, project_root)
    return project_root


def test_indexes_vanilla_js_fixture(tmp_path):
    project_root = _copy_fixture(JS_FIXTURE_ROOT, tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    rows = {
        row[0]: (row[1], row[2])
        for row in conn.execute(
            "SELECT qualified_name, kind, language FROM symbols"
        ).fetchall()
    }

    assert rows.get("app.widget.formatLabel") == ("function", "javascript")
    assert rows.get("app.widget.Widget") == ("class", "javascript")


def test_does_not_scan_node_modules_for_js_project(tmp_path):
    project_root = _copy_fixture(JS_FIXTURE_ROOT, tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    paths = {row[0] for row in conn.execute("SELECT path FROM files").fetchall()}

    assert not any(path.startswith("node_modules/") for path in paths)
    assert "app/widget.js" in paths


def test_indexes_react_ts_fixture_at_generic_language_level(tmp_path):
    project_root = _copy_fixture(REACT_FIXTURE_ROOT, tmp_path)
    config = load_config(project_root)
    conn = get_connection(project_root)

    run_scan(conn, project_root, config)

    rows = {
        row[0]: (row[1], row[2])
        for row in conn.execute(
            "SELECT qualified_name, kind, language FROM symbols"
        ).fetchall()
    }

    assert rows.get("src.Widget.Widget") == ("component", "typescript")

    paths = {row[0] for row in conn.execute("SELECT path FROM files").fetchall()}
    assert not any(path.startswith("node_modules/") for path in paths)
