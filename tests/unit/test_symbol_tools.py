import shutil
from pathlib import Path

from project_mcp.tools.symbols import (
    find_symbol,
    get_dependencies,
    get_dependents,
    get_symbol_context,
)

FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "python" / "sample_project"
)


def _copy_fixture(tmp_path: Path) -> Path:
    project_root = tmp_path / "sample_project"
    shutil.copytree(FIXTURE_ROOT, project_root)
    return project_root


def test_find_symbol_matches_by_name_substring_case_insensitively(tmp_path):
    project_root = _copy_fixture(tmp_path)

    results = find_symbol(project_root, "widget")

    qualified_names = {r["qualified_name"] for r in results}
    assert "app.models.Widget" in qualified_names
    for r in results:
        assert r["file"]


def test_get_symbol_context_returns_full_details_for_exact_match(tmp_path):
    project_root = _copy_fixture(tmp_path)

    context = get_symbol_context(project_root, "app.models.Widget")

    assert context["found"] is True
    assert context["symbol"]["kind"] == "class"
    assert context["symbol"]["file"] == "app/models.py"


def test_get_symbol_context_returns_not_found_for_missing_symbol(tmp_path):
    project_root = _copy_fixture(tmp_path)

    context = get_symbol_context(project_root, "app.models.DoesNotExist")

    assert context["found"] is False
    assert context["symbol"] is None


def test_get_dependencies_returns_import_targets_for_a_module(tmp_path):
    project_root = _copy_fixture(tmp_path)

    dependencies = get_dependencies(project_root, "tests.test_models")

    assert {
        "target": "app/models.py",
        "relationship_type": "imports",
        "confidence": "high",
    } in dependencies


def test_get_dependencies_returns_inheritance_target_for_a_class(tmp_path):
    project_root = _copy_fixture(tmp_path)
    (project_root / "app" / "shapes.py").write_text(
        "class Shape:\n"
        "    pass\n"
        "\n"
        "\n"
        "class Circle(Shape):\n"
        "    pass\n"
    )

    dependencies = get_dependencies(project_root, "app.shapes.Circle")

    assert {
        "target": "app.shapes.Shape",
        "relationship_type": "inherits",
        "confidence": "high",
    } in dependencies


def test_get_dependents_returns_import_sources_for_a_module(tmp_path):
    project_root = _copy_fixture(tmp_path)

    dependents = get_dependents(project_root, "app.models")

    assert {
        "source": "tests/test_models.py",
        "relationship_type": "imports",
        "confidence": "high",
    } in dependents


def test_get_dependents_returns_inheritance_sources_for_a_class(tmp_path):
    project_root = _copy_fixture(tmp_path)
    (project_root / "app" / "shapes.py").write_text(
        "class Shape:\n"
        "    pass\n"
        "\n"
        "\n"
        "class Circle(Shape):\n"
        "    pass\n"
    )

    dependents = get_dependents(project_root, "app.shapes.Shape")

    assert {
        "source": "app.shapes.Circle",
        "relationship_type": "inherits",
        "confidence": "high",
    } in dependents
