import shutil
from pathlib import Path

from project_mcp.tools.tests import get_test_summary, get_tests_for

FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "python" / "sample_project"
)


def _copy_fixture(tmp_path: Path) -> Path:
    project_root = tmp_path / "sample_project"
    shutil.copytree(FIXTURE_ROOT, project_root)
    return project_root


def test_get_tests_for_returns_relationships_with_confidence_and_evidence(tmp_path):
    project_root = _copy_fixture(tmp_path)

    tests_for = get_tests_for(project_root, "app.models")

    assert {
        "test_file": "tests/test_models.py",
        "confidence": "high",
        "evidence": ["direct_import"],
    } in tests_for


def test_get_tests_for_returns_empty_list_when_no_evidence_found(tmp_path):
    project_root = _copy_fixture(tmp_path)

    tests_for = get_tests_for(project_root, "app")

    assert tests_for == []


def test_get_test_summary_returns_totals_and_confidence_breakdown(tmp_path):
    project_root = _copy_fixture(tmp_path)

    summary = get_test_summary(project_root)

    assert summary["total_tests"] == 1
    assert summary["total_relationships"] == 1
    assert summary["by_confidence"] == {"high": 1}
