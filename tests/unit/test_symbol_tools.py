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


def _add_migration_defining(project_root: Path, class_name: str) -> None:
    migrations = project_root / "app" / "migrations"
    migrations.mkdir()
    (migrations / "__init__.py").write_text("")
    (migrations / "0001_initial.py").write_text(f"class {class_name}:\n    pass\n")


def test_find_symbol_leaves_out_migrations_unless_asked(tmp_path):
    project_root = _copy_fixture(tmp_path)
    _add_migration_defining(project_root, "WidgetMigrationHelper")

    default = {r["qualified_name"] for r in find_symbol(project_root, "widget")}
    included = {
        r["qualified_name"]
        for r in find_symbol(project_root, "widget", include_migrations=True)
    }

    assert "app.models.Widget" in default
    assert not any("migrations" in name for name in default)
    assert any("migrations" in name for name in included)


def test_find_symbol_ranks_exact_name_then_prefix_then_substring(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "things.py").write_text(
        "class AWidget:\n    pass\n\n\nclass Widget:\n    pass\n\n\nclass WidgetZ:\n    pass\n"
    )

    results = find_symbol(tmp_path, "widget")

    assert [r["name"] for r in results] == ["Widget", "WidgetZ", "AWidget"]


def test_find_symbol_filters_by_kind(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "widgets.py").write_text(
        "class Widget:\n    pass\n\n\ndef widget_factory():\n    pass\n"
    )

    classes = find_symbol(tmp_path, "widget", kind="class")
    functions = find_symbol(tmp_path, "widget", kind="function")
    modules = find_symbol(tmp_path, "widgets", kind="module")

    assert [r["name"] for r in classes] == ["Widget"]
    assert [r["name"] for r in functions] == ["widget_factory"]
    assert [r["qualified_name"] for r in modules] == ["app.widgets"]


def test_find_symbol_pages_with_limit_and_offset(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "widgets.py").write_text(
        "".join(f"class Widget{i}:\n    pass\n\n\n" for i in range(5))
    )

    everything = [r["name"] for r in find_symbol(tmp_path, "widget", kind="class")]
    first = [r["name"] for r in find_symbol(tmp_path, "widget", kind="class", limit=2)]
    second = [
        r["name"]
        for r in find_symbol(tmp_path, "widget", kind="class", limit=2, offset=2)
    ]

    assert len(everything) == 5
    assert first == everything[:2]
    assert second == everything[2:4]


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


def test_find_symbol_lists_fields_after_other_symbol_kinds(tmp_path):
    project_root = _copy_fixture(tmp_path)
    (project_root / "app" / "aa_payment.py").write_text(
        "class Payment:\n"
        "    status = 'new'\n"
    )
    (project_root / "app" / "zz_reports.py").write_text(
        "def status_report():\n"
        "    return 1\n"
    )

    results = find_symbol(project_root, "status")

    kinds = [r["kind"] for r in results]
    assert "field" in kinds and "function" in kinds
    assert kinds.index("function") < kinds.index("field")
    assert kinds[kinds.index("field"):] == ["field"] * kinds.count("field")


def test_get_dependents_returns_methods_that_read_a_model_field_via_self(tmp_path):
    project_root = _copy_fixture(tmp_path)
    (project_root / "app" / "payments.py").write_text(
        "from django.db import models\n"
        "\n"
        "\n"
        "class Payment(models.Model):\n"
        "    gateway_captured_card_number = models.CharField(max_length=32)\n"
        "\n"
        "    def masked(self):\n"
        "        return self.gateway_captured_card_number[-4:]\n"
        "\n"
        "    @property\n"
        "    def has_card(self):\n"
        "        return bool(self.gateway_captured_card_number)\n"
    )

    dependents = get_dependents(
        project_root, "app.payments.Payment.gateway_captured_card_number"
    )

    assert {
        "source": "app.payments.Payment.masked",
        "relationship_type": "references",
        "confidence": "high",
    } in dependents
    assert {
        "source": "app.payments.Payment.has_card",
        "relationship_type": "references",
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


def test_find_symbol_treats_like_wildcards_in_the_query_literally(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "users.py").write_text(
        "def get_user():\n    pass\n\n\ndef getXuser():\n    pass\n"
    )

    underscore = find_symbol(tmp_path, "get_user")
    percent = find_symbol(tmp_path, "%")

    assert [r["name"] for r in underscore] == ["get_user"]
    assert percent == []


def _watch_project(root: Path) -> Path:
    (root / "cms").mkdir()
    (root / "cms" / "models.py").write_text(
        "class Watch:\n    pass\n\n\nclass Other:\n    pass\n"
    )
    (root / "cms" / "forms.py").write_text(
        "from cms.models import Watch\n\n\n"
        "class WatchForm:\n    class Meta:\n        model = Watch\n"
    )
    (root / "cms" / "views.py").write_text(
        "from cms.models import Watch as W\n\n\ndef show():\n    return W\n"
    )
    (root / "cms" / "unrelated.py").write_text("from cms.models import Other\n")
    return root


def _importers(rows: list[dict]) -> list[str]:
    return sorted(row["source"] for row in rows if row["relationship_type"] == "imports")


def test_get_dependents_lists_the_files_that_import_a_symbol(tmp_path):
    project_root = _watch_project(tmp_path)

    rows = get_dependents(project_root, "cms.models.Watch")

    assert _importers(rows) == ["cms/forms.py", "cms/views.py"]
    assert all(row["confidence"] == "high" for row in rows)


def test_get_dependents_keeps_symbol_importers_after_the_symbols_file_is_edited(tmp_path):
    import time

    project_root = _watch_project(tmp_path)
    assert _importers(get_dependents(project_root, "cms.models.Watch")) == [
        "cms/forms.py",
        "cms/views.py",
    ]

    time.sleep(0.01)
    (project_root / "cms" / "models.py").write_text(
        "class Watch:\n    def size(self):\n        return 1\n\n\nclass Other:\n    pass\n"
    )

    assert _importers(get_dependents(project_root, "cms.models.Watch")) == [
        "cms/forms.py",
        "cms/views.py",
    ]
