import shutil
from pathlib import Path

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
