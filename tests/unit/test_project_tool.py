import shutil
from pathlib import Path

from project_mcp.db import get_connection
from project_mcp.tools.project import get_project_overview

FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "python" / "sample_project"
)


def _copy_fixture(tmp_path: Path) -> Path:
    project_root = tmp_path / "sample_project"
    shutil.copytree(FIXTURE_ROOT, project_root)
    return project_root


def test_get_project_overview_indexes_and_reports_status(tmp_path):
    project_root = _copy_fixture(tmp_path)

    overview = get_project_overview(project_root)

    assert overview["index_status"]["status"] == "fresh"
    assert overview["project"]["root_path"] == str(project_root)


def test_get_project_overview_reports_languages_and_file_counts(tmp_path):
    project_root = _copy_fixture(tmp_path)

    overview = get_project_overview(project_root)

    assert "python" in overview["languages"]
    assert overview["file_counts"]["source"] >= 1
    assert overview["file_counts"]["test"] >= 1


def test_get_project_overview_reports_manifests(tmp_path):
    project_root = _copy_fixture(tmp_path)

    overview = get_project_overview(project_root)

    assert "pyproject.toml" in overview["manifests"]


def test_get_project_overview_infers_source_and_test_roots(tmp_path):
    project_root = _copy_fixture(tmp_path)

    overview = get_project_overview(project_root)

    assert "app" in overview["source_roots"]
    assert "tests" in overview["test_roots"]


def test_get_project_overview_omits_excluded_dirs_from_roots(tmp_path):
    project_root = _copy_fixture(tmp_path)

    overview = get_project_overview(project_root)

    assert ".venv" not in overview["source_roots"]
    assert "node_modules" not in overview["source_roots"]


def test_get_project_overview_only_counts_current_project_files(tmp_path):
    project_root = _copy_fixture(tmp_path)

    baseline = get_project_overview(project_root)
    baseline_source_count = baseline["file_counts"]["source"]

    conn = get_connection(project_root)
    other_project_id = conn.execute(
        "INSERT INTO projects (root_path, created_at) VALUES (?, ?)",
        ("/tmp/other-project", "2026-01-01"),
    ).lastrowid
    conn.execute(
        "INSERT INTO files (project_id, path, language, file_kind) VALUES (?, ?, ?, ?)",
        (other_project_id, "other/leaked.py", "python", "source"),
    )
    conn.commit()
    conn.close()

    overview = get_project_overview(project_root)

    assert overview["file_counts"]["source"] == baseline_source_count
    assert "other" not in overview["source_roots"]


def test_get_project_overview_lists_only_manifests_of_registered_plugins(tmp_path):
    from project_mcp.plugins.python.descriptor import DESCRIPTOR as python
    from project_mcp.plugins.registry import PluginRegistry

    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'demo'\n")
    registry = PluginRegistry()
    registry.register(python)

    overview = get_project_overview(tmp_path, registry=registry)

    assert overview["manifests"] == ["pyproject.toml"]


def test_indexing_stores_the_dependencies_of_registered_plugins_only(tmp_path):
    from project_mcp.plugins.python.descriptor import DESCRIPTOR as python
    from project_mcp.plugins.registry import PluginRegistry

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\ndependencies = ['requests>=2']\n"
    )
    (tmp_path / "Cargo.toml").write_text('[dependencies]\nserde = "1"\n')
    registry = PluginRegistry()
    registry.register(python)

    get_project_overview(tmp_path, registry=registry)

    assert get_connection(tmp_path).execute(
        "SELECT name, ecosystem FROM dependencies"
    ).fetchall() == [("requests", "python")]


def test_get_project_overview_lists_active_plugins_and_uncovered_languages(tmp_path):
    from project_mcp.plugins.registry import builtin_registry

    (tmp_path / "app.py").write_text("def run():\n    pass\n")
    (tmp_path / "lib.rs").write_text("pub fn run() {}\n")
    registry = builtin_registry()
    registry.disable("rust")

    overview = get_project_overview(tmp_path, registry=registry)

    assert overview["active_plugins"] == ["python", "javascript", "django", "astro"]
    assert overview["uncovered_languages"] == {"rust": 1}
