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


def _order_project(root: Path) -> Path:
    (root / "app").mkdir()
    (root / "app" / "models.py").write_text(
        "class Order:\n"
        "    def refund(self):\n"
        "        return 1\n"
        "\n"
        "    def cancel(self):\n"
        "        return 2\n"
        "\n"
        "    def unused(self):\n"
        "        return 3\n"
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_orders.py").write_text(
        "from app.models import Order\n"
        "\n"
        "\n"
        "class TestRefund:\n"
        "    def test_refund(self):\n"
        "        order = Order()\n"
        "        assert order.refund()\n"
        "\n"
        "\n"
        "def test_cancel():\n"
        "    assert Order().cancel()\n"
    )
    (root / "tests" / "test_misc.py").write_text(
        "from app.models import Order\n\n\ndef test_builds():\n    assert Order\n"
    )
    return root


def test_get_tests_for_a_method_names_the_tests_that_reference_it(tmp_path):
    project_root = _order_project(tmp_path)

    tests_for = get_tests_for(project_root, "app.models.Order.refund")

    assert tests_for == [
        {
            "test_file": "tests/test_orders.py",
            "confidence": "high",
            "evidence": ["symbol_reference"],
            "tests": ["tests.test_orders.TestRefund.test_refund"],
        }
    ]


def test_get_tests_for_a_method_called_on_a_constructor_expression(tmp_path):
    project_root = _order_project(tmp_path)

    (row,) = get_tests_for(project_root, "app.models.Order.cancel")

    assert row["tests"] == ["tests.test_orders.test_cancel"]


def test_get_tests_for_a_method_nothing_references_stays_empty(tmp_path):
    project_root = _order_project(tmp_path)

    assert get_tests_for(project_root, "app.models.Order.unused") == []


def test_get_tests_for_a_method_caps_the_tests_it_names_per_file(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text(
        "class Box:\n    def value(self):\n        return 1\n"
    )
    (tmp_path / "tests").mkdir()
    many = "".join(
        f"def test_value_{i:02d}():\n    box = Box()\n    assert box.value()\n\n\n"
        for i in range(12)
    )
    (tmp_path / "tests" / "test_models.py").write_text(
        "from app.models import Box\n\n\n" + many
    )

    (row,) = get_tests_for(tmp_path, "app.models.Box.value")

    assert row["tests"] == [f"tests.test_models.test_value_{i:02d}" for i in range(5)]
    assert row["tests_total"] == 12


def test_get_tests_for_a_method_leaves_helpers_out_of_the_tests_it_names(tmp_path):
    project_root = _order_project(tmp_path)
    (project_root / "tests" / "test_helpers.py").write_text(
        "from app.models import Order\n"
        "\n"
        "\n"
        "class TestCancel:\n"
        "    def _hit(self):\n"
        "        return Order().cancel()\n"
        "\n"
        "    def test_cancel(self):\n"
        "        assert self._hit()\n"
        "\n"
        "    def test_direct(self):\n"
        "        assert Order().cancel()\n"
    )

    tests_for = get_tests_for(project_root, "app.models.Order.cancel")

    helpers_file = next(t for t in tests_for if t["test_file"] == "tests/test_helpers.py")
    assert helpers_file["tests"] == ["tests.test_helpers.TestCancel.test_direct"]


def test_get_tests_for_a_method_reached_only_through_a_helper_keeps_the_file(tmp_path):
    project_root = _order_project(tmp_path)
    (project_root / "tests" / "test_only_helper.py").write_text(
        "from app.models import Order\n"
        "\n"
        "\n"
        "def make_cancelled():\n"
        "    return Order().cancel()\n"
    )

    tests_for = get_tests_for(project_root, "app.models.Order.cancel")

    entry = next(t for t in tests_for if t["test_file"] == "tests/test_only_helper.py")
    assert entry["confidence"] == "high"
    assert "tests" not in entry
