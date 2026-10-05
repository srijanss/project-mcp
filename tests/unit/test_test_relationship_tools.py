import shutil
from pathlib import Path

import pytest

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


def _box_project(root: Path, tests: int) -> Path:
    (root / "app").mkdir()
    (root / "app" / "models.py").write_text(
        "class Box:\n    def value(self):\n        return 1\n"
    )
    (root / "tests").mkdir()
    many = "".join(
        f"def test_value_{i:02d}():\n    box = Box()\n    assert box.value()\n\n\n"
        for i in range(tests)
    )
    (root / "tests" / "test_models.py").write_text(
        "from app.models import Box\n\n\n" + many
    )
    return root


def test_get_tests_for_a_method_caps_the_tests_it_names_per_file(tmp_path):
    _box_project(tmp_path, tests=12)

    (row,) = get_tests_for(tmp_path, "app.models.Box.value")

    assert row["tests"] == [f"tests.test_models.test_value_{i:02d}" for i in range(5)]
    assert row["tests_total"] == 12


def test_get_tests_for_a_method_with_limit_zero_names_every_test(tmp_path):
    _box_project(tmp_path, tests=12)

    (row,) = get_tests_for(tmp_path, "app.models.Box.value", limit=0)

    assert row["tests"] == [f"tests.test_models.test_value_{i:02d}" for i in range(12)]
    assert "tests_total" not in row


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
    assert "tests.test_helpers.TestCancel._hit" not in helpers_file["tests"]


def test_get_tests_for_a_method_reached_only_through_a_helper_marks_the_file_as_helper_evidence(
    tmp_path,
):
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
    assert entry == {
        "test_file": "tests/test_only_helper.py",
        "confidence": "medium",
        "evidence": ["helper_reference"],
    }


def _src_layout_project(root: Path, source_root: str = "src") -> Path:
    (root / ".project-mcp").mkdir()
    (root / ".project-mcp" / "config.toml").write_text(
        f'source_roots = ["{source_root}"]\n'
    )
    package = root / "src" / "shop"
    (package / "tests").mkdir(parents=True)
    (package / "billing.py").write_text(
        "class Invoice:\n    def total(self):\n        return 1\n"
    )
    (package / "tests" / "test_billing.py").write_text(
        "from shop.billing import Invoice\n"
        "\n"
        "\n"
        "def test_total():\n"
        "    assert Invoice().total()\n"
    )
    return root


def test_get_tests_for_resolves_imports_relative_to_a_source_root(tmp_path):
    project_root = _src_layout_project(tmp_path)

    tests_for = get_tests_for(project_root, "src.shop.billing.Invoice.total")

    assert tests_for == [
        {
            "test_file": "src/shop/tests/test_billing.py",
            "confidence": "high",
            "evidence": ["symbol_reference"],
            "tests": ["src.shop.tests.test_billing.test_total"],
        }
    ]


def test_get_tests_for_accepts_a_source_root_written_with_a_leading_dot_slash(tmp_path):
    project_root = _src_layout_project(tmp_path, source_root="./src")

    (row,) = get_tests_for(project_root, "src.shop.billing.Invoice.total")

    assert row["tests"] == ["src.shop.tests.test_billing.test_total"]


def _payments_project(root: Path) -> Path:
    (root / "app").mkdir()
    (root / "app" / "payments.py").write_text(
        "class Api:\n"
        "    def process_payment(self):\n"
        "        return self._post()\n"
        "\n"
        "    def _post(self):\n"
        "        return self._sign()\n"
        "\n"
        "    def _sign(self):\n"
        "        return 'jwt'\n"
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_payments.py").write_text(
        "from app.payments import Api\n"
        "\n"
        "\n"
        "class TestProcessPayment:\n"
        "    def test_pays(self):\n"
        "        assert Api().process_payment()\n"
    )
    return root


def test_get_tests_for_a_private_method_names_tests_that_reach_it_through_its_callers(
    tmp_path,
):
    project_root = _payments_project(tmp_path)

    tests_for = get_tests_for(project_root, "app.payments.Api._sign")

    assert tests_for == [
        {
            "test_file": "tests/test_payments.py",
            "confidence": "medium",
            "evidence": ["indirect_call"],
            "via": ["app.payments.Api.process_payment", "app.payments.Api._post"],
            "tests": ["tests.test_payments.TestProcessPayment.test_pays"],
        }
    ]


def _django_checkout_project(root: Path) -> Path:
    (root / ".project-mcp").mkdir()
    (root / ".project-mcp" / "config.toml").write_text('source_roots = ["src"]\n')
    app = root / "src" / "shop" / "checkout"
    (app / "tests").mkdir(parents=True)
    (app / "__init__.py").write_text("")
    (app / "views.py").write_text(
        "class CardPayment:\n    def get(self, request):\n        return None\n"
    )
    (app / "urls.py").write_text(
        "from django.urls import path\n"
        "\n"
        "from . import views\n"
        "\n"
        'app_name = "checkout"\n'
        "\n"
        "urlpatterns = [\n"
        '    path("card/", views.CardPayment.as_view(), name="card-payment"),\n'
        "]\n"
    )
    (app / "tests" / "test_views.py").write_text(
        "from django.urls import reverse\n"
        "\n"
        "\n"
        "class TestCardPayment:\n"
        "    def test_shows_the_form(self, client):\n"
        '        response = client.get(reverse("checkout:card-payment"))\n'
        "        assert response.status_code == 200\n"
    )
    return root


def test_get_tests_for_a_django_view_names_tests_that_reverse_its_url_name(tmp_path):
    project_root = _django_checkout_project(tmp_path)

    tests_for = get_tests_for(project_root, "src.shop.checkout.views.CardPayment")

    assert tests_for == [
        {
            "test_file": "src/shop/checkout/tests/test_views.py",
            "confidence": "high",
            "evidence": ["url_reverse"],
            "tests": [
                "src.shop.checkout.tests.test_views.TestCardPayment.test_shows_the_form"
            ],
        }
    ]


def test_get_tests_for_names_a_test_requesting_a_url_reversed_at_module_level(
    tmp_path,
):
    project_root = _django_checkout_project(tmp_path)
    (project_root / "src" / "shop" / "checkout" / "tests" / "test_views.py").write_text(
        "from django.urls import reverse\n"
        "\n"
        'URL = reverse("checkout:card-payment")\n'
        "\n"
        "\n"
        "def test_shows_the_form(client):\n"
        "    assert client.get(URL)\n"
    )

    (row,) = get_tests_for(project_root, "src.shop.checkout.views.CardPayment")

    assert row["tests"] == ["src.shop.checkout.tests.test_views.test_shows_the_form"]


def test_get_tests_for_a_django_view_names_only_tests_requesting_the_reversed_url(
    tmp_path,
):
    project_root = _django_checkout_project(tmp_path)
    (project_root / "src" / "shop" / "checkout" / "tests" / "test_views.py").write_text(
        "from django.urls import reverse\n"
        "\n"
        "\n"
        "def test_url_is_stable():\n"
        '    assert reverse("checkout:card-payment") == "/card/"\n'
        "\n"
        "\n"
        "def test_shows_the_form(client):\n"
        '    url = reverse("checkout:card-payment")\n'
        "    response = client.get(url)\n"
        "    assert response.status_code == 200\n"
    )

    (row,) = get_tests_for(project_root, "src.shop.checkout.views.CardPayment")

    assert row["tests"] == ["src.shop.checkout.tests.test_views.test_shows_the_form"]


def test_get_tests_for_a_django_view_follows_the_namespace_an_include_gives_it(
    tmp_path,
):
    project_root = _django_checkout_project(tmp_path)
    app = project_root / "src" / "shop" / "checkout"
    (app / "urls.py").write_text(
        "from django.urls import path\n"
        "\n"
        "from . import views\n"
        "\n"
        "urlpatterns = [\n"
        '    path("card/", views.CardPayment.as_view(), name="card-payment"),\n'
        "]\n"
    )
    (project_root / "src" / "shop" / "urls.py").write_text(
        "from django.urls import include, path\n"
        "\n"
        "urlpatterns = [\n"
        '    path("pay/", include("shop.checkout.urls", namespace="pay")),\n'
        "]\n"
    )
    (app / "tests" / "test_views.py").write_text(
        "from django.urls import reverse\n"
        "\n"
        "\n"
        "def test_shows_the_form(client):\n"
        '    assert client.get(reverse("pay:card-payment"))\n'
    )

    (row,) = get_tests_for(project_root, "src.shop.checkout.views.CardPayment")

    assert row["tests"] == ["src.shop.checkout.tests.test_views.test_shows_the_form"]


def test_get_tests_for_rejects_a_negative_limit(tmp_path):
    _box_project(tmp_path, tests=7)

    with pytest.raises(ValueError, match="limit"):
        get_tests_for(tmp_path, "app.models.Box.value", limit=-5)


def test_get_tests_for_keeps_a_guessed_helper_only_file_at_low_confidence(tmp_path):
    project_root = _order_project(tmp_path)
    (project_root / "tests" / "test_guess.py").write_text(
        "from app.models import Order\n\n\ndef cancel_it(order):\n    return order.cancel()\n"
    )

    tests_for = get_tests_for(project_root, "app.models.Order.cancel")

    entry = next(t for t in tests_for if t["test_file"] == "tests/test_guess.py")
    assert entry == {
        "test_file": "tests/test_guess.py",
        "confidence": "low",
        "evidence": ["helper_reference"],
    }


def _call_chain_project(root: Path) -> Path:
    (root / "app").mkdir()
    (root / "app" / "chain.py").write_text(
        "def target():\n    return 1\n\n\n"
        "def one():\n    return target()\n\n\n"
        "def two():\n    return one()\n\n\n"
        "def three():\n    return two()\n\n\n"
        "def four():\n    return three()\n"
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_three.py").write_text(
        "from app.chain import three\n\n\ndef test_three():\n    assert three()\n"
    )
    (root / "tests" / "test_four.py").write_text(
        "from app.chain import four\n\n\ndef test_four():\n    assert four()\n"
    )
    return root


def test_get_tests_for_follows_callers_at_most_three_calls_deep(tmp_path):
    project_root = _call_chain_project(tmp_path)

    tests_for = get_tests_for(project_root, "app.chain.target")

    assert [row["test_file"] for row in tests_for] == ["tests/test_three.py"]
    assert tests_for[0]["via"] == ["app.chain.three", "app.chain.two", "app.chain.one"]


def test_get_tests_for_walks_mutually_recursive_callers_once(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "loop.py").write_text(
        "def target(n):\n    return target(n - 1) if n else 0\n\n\n"
        "def ping(n):\n    return pong(n) + target(n)\n\n\n"
        "def pong(n):\n    return ping(n - 1) if n else 0\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_loop.py").write_text(
        "from app.loop import pong\n\n\ndef test_pong():\n    assert pong(2) == 0\n"
    )

    tests_for = get_tests_for(tmp_path, "app.loop.target")

    assert tests_for == [
        {
            "test_file": "tests/test_loop.py",
            "confidence": "medium",
            "evidence": ["indirect_call"],
            "via": ["app.loop.pong", "app.loop.ping"],
            "tests": ["tests.test_loop.test_pong"],
        }
    ]


def test_get_tests_for_merges_every_call_path_that_reaches_the_same_test_file(
    tmp_path,
):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "payments.py").write_text(
        "def _post():\n    return 1\n\n\n"
        "def create_capture_context():\n    return _post()\n\n\n"
        "def process_payment():\n    return _post()\n\n\n"
        "def charge():\n    return process_payment()\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_payments.py").write_text(
        "from app.payments import charge, create_capture_context, process_payment\n"
        "\n\n"
        "def test_capture():\n    assert create_capture_context()\n\n\n"
        "def test_process():\n    assert process_payment()\n\n\n"
        "def test_charge():\n    assert charge()\n"
    )

    tests_for = get_tests_for(tmp_path, "app.payments._post")

    assert len(tests_for) == 1
    assert tests_for[0]["tests"] == [
        "tests.test_payments.test_capture",
        "tests.test_payments.test_process",
        "tests.test_payments.test_charge",
    ]
    assert tests_for[0]["paths"] == [
        {
            "via": ["app.payments.create_capture_context"],
            "tests": ["tests.test_payments.test_capture"],
        },
        {
            "via": ["app.payments.process_payment"],
            "tests": ["tests.test_payments.test_process"],
        },
        {
            "via": ["app.payments.charge", "app.payments.process_payment"],
            "tests": ["tests.test_payments.test_charge"],
        },
    ]


def test_get_tests_for_caps_the_tests_each_merged_call_path_names(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "payments.py").write_text(
        "def _post():\n    return 1\n\n\n"
        "def capture():\n    return _post()\n\n\n"
        "def refund():\n    return _post()\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_payments.py").write_text(
        "from app.payments import capture, refund\n\n\n"
        + "".join(
            f"def test_{name}_{n}():\n    assert {name}()\n\n\n"
            for name in ("capture", "refund")
            for n in range(3)
        )
    )

    tests_for = get_tests_for(tmp_path, "app.payments._post", limit=2)

    assert [path["tests"] for path in tests_for[0]["paths"]] == [
        ["tests.test_payments.test_capture_0", "tests.test_payments.test_capture_1"],
        ["tests.test_payments.test_refund_0", "tests.test_payments.test_refund_1"],
    ]
    assert tests_for[0]["tests_total"] == 6


def test_get_tests_for_names_a_test_from_every_path_in_the_capped_tests(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "payments.py").write_text(
        "def _sign():\n    return 1\n\n\n"
        "def _post():\n    return _sign()\n\n\n"
        "def charge():\n    return _post()\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_payments.py").write_text(
        "from app.payments import _post, charge\n\n\n"
        + "".join(f"def test_a_charge_{n}():\n    assert charge()\n\n\n" for n in range(3))
        + "def test_z_signing():\n    assert _post()\n"
    )

    tests_for = get_tests_for(tmp_path, "app.payments._sign", limit=2)

    assert "tests.test_payments.test_z_signing" in tests_for[0]["tests"]
    assert tests_for[0]["tests_total"] == 4


def test_get_tests_for_names_tests_in_other_files_that_call_a_test_helper(tmp_path):
    project_root = _order_project(tmp_path)
    (project_root / "tests" / "test_helpers.py").write_text(
        "from app.models import Order\n\n\ndef make_unused():\n    return Order().unused()\n"
    )
    (project_root / "tests" / "test_checkout.py").write_text(
        "from tests.test_helpers import make_unused\n\n\n"
        "def test_checkout():\n    assert make_unused()\n"
    )

    tests_for = get_tests_for(project_root, "app.models.Order.unused")

    assert tests_for == [
        {
            "test_file": "tests/test_checkout.py",
            "confidence": "medium",
            "evidence": ["helper_call"],
            "via": ["tests.test_helpers.make_unused"],
            "tests": ["tests.test_checkout.test_checkout"],
        },
        {
            "test_file": "tests/test_helpers.py",
            "confidence": "medium",
            "evidence": ["helper_reference"],
        },
    ]


def test_get_tests_for_adds_tests_reaching_a_symbol_through_a_helper_in_the_same_file(
    tmp_path,
):
    project_root = _order_project(tmp_path)
    (project_root / "tests" / "test_helpers.py").write_text(
        "from app.models import Order\n"
        "\n"
        "\n"
        "def _hit():\n"
        "    return Order().cancel()\n"
        "\n"
        "\n"
        "def test_cancel():\n"
        "    assert _hit()\n"
        "\n"
        "\n"
        "def test_direct():\n"
        "    assert Order().cancel()\n"
    )

    tests_for = get_tests_for(project_root, "app.models.Order.cancel")

    helpers_file = next(t for t in tests_for if t["test_file"] == "tests/test_helpers.py")
    assert helpers_file["tests"] == [
        "tests.test_helpers.test_direct",
        "tests.test_helpers.test_cancel",
    ]
    assert helpers_file["evidence"] == ["symbol_reference", "helper_call"]


def test_get_tests_for_names_tests_calling_a_symbol_before_those_reaching_it_through_a_helper(
    tmp_path,
):
    project_root = _order_project(tmp_path)
    (project_root / "tests" / "test_helpers.py").write_text(
        "from app.models import Order\n"
        "\n"
        "\n"
        "def _hit():\n"
        "    return Order().cancel()\n"
        "\n"
        "\n"
        + "".join(f"def test_a_via_helper_{n}():\n    assert _hit()\n\n\n" for n in range(5))
        + "def test_z_direct():\n    assert Order().cancel()\n"
    )

    tests_for = get_tests_for(project_root, "app.models.Order.cancel")

    helpers_file = next(t for t in tests_for if t["test_file"] == "tests/test_helpers.py")
    assert helpers_file["tests"][0] == "tests.test_helpers.test_z_direct"
    assert helpers_file["tests_total"] == 6


def _mocked_checkout_project(root: Path) -> Path:
    (root / "app").mkdir()
    (root / "app" / "payments.py").write_text(
        "def _post():\n    return 1\n\n\n"
        "def process_payment():\n    return _post()\n"
    )
    (root / "app" / "checkout.py").write_text(
        "from app.payments import process_payment\n\n\n"
        "def checkout():\n    return process_payment()\n"
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_checkout.py").write_text(
        "from unittest.mock import patch\n"
        "\n"
        "from app.checkout import checkout\n"
        "\n"
        "\n"
        "def test_checkout_real():\n"
        "    assert checkout()\n"
        "\n"
        "\n"
        '@patch("app.checkout.process_payment")\n'
        "def test_checkout_mocked(process_payment):\n"
        "    assert checkout()\n"
    )
    return root


def test_get_tests_for_sets_aside_tests_that_mock_a_call_on_the_way(tmp_path):
    project_root = _mocked_checkout_project(tmp_path)

    tests_for = get_tests_for(project_root, "app.payments._post")

    assert tests_for == [
        {
            "test_file": "tests/test_checkout.py",
            "confidence": "medium",
            "evidence": ["indirect_call"],
            "via": ["app.checkout.checkout", "app.payments.process_payment"],
            "tests": ["tests.test_checkout.test_checkout_real"],
            "mocked": ["tests.test_checkout.test_checkout_mocked"],
        }
    ]


def test_get_tests_for_sets_aside_tests_whose_conftest_fixture_mocks_a_call_on_the_way(
    tmp_path,
):
    project_root = _mocked_checkout_project(tmp_path)
    (project_root / "tests" / "conftest.py").write_text(
        "import pytest\n"
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def paid(mocker):\n"
        '    return mocker.patch("app.checkout.process_payment")\n'
    )
    (project_root / "tests" / "test_paid.py").write_text(
        "from app.checkout import checkout\n"
        "\n"
        "\n"
        "def test_checkout_paid(paid):\n"
        "    assert checkout()\n"
    )

    tests_for = get_tests_for(project_root, "app.payments._post")

    assert tests_for[1] == {
        "test_file": "tests/test_paid.py",
        "confidence": "low",
        "evidence": ["indirect_call", "mocked"],
        "mocked": ["tests.test_paid.test_checkout_paid"],
    }


def test_get_tests_for_sets_aside_tests_patching_a_call_on_the_way_on_an_instance(
    tmp_path,
):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "gateway.py").write_text(
        "class Gateway:\n"
        "    def _sign(self):\n"
        "        return 1\n"
        "\n"
        "    def _post(self):\n"
        "        return self._sign()\n"
        "\n"
        "    def charge(self):\n"
        "        return self._post()\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_gateway.py").write_text(
        "from app.gateway import Gateway\n"
        "\n"
        "\n"
        "def test_charge(mocker):\n"
        "    gateway = Gateway()\n"
        '    mocker.patch.object(gateway, "_post")\n'
        "    assert gateway.charge()\n"
    )

    tests_for = get_tests_for(tmp_path, "app.gateway.Gateway._sign")

    assert tests_for == [
        {
            "test_file": "tests/test_gateway.py",
            "confidence": "low",
            "evidence": ["indirect_call", "mocked"],
            "mocked": ["tests.test_gateway.test_charge"],
        }
    ]


def test_get_tests_for_sets_aside_tests_patching_the_class_whose_method_is_on_the_way(
    tmp_path,
):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "cybersource.py").write_text(
        "class CybersourceApi:\n"
        "    def _sign(self):\n"
        "        return 1\n"
        "\n"
        "    def post(self):\n"
        "        return self._sign()\n"
    )
    (tmp_path / "app" / "fiserv.py").write_text(
        "from app.cybersource import CybersourceApi\n"
        "\n"
        "\n"
        "class FiservGateway:\n"
        "    def charge(self):\n"
        "        return CybersourceApi().post()\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_fiserv.py").write_text(
        "from app.fiserv import FiservGateway\n"
        "\n"
        "\n"
        "def test_charge(mocker):\n"
        '    mocker.patch("app.fiserv.CybersourceApi")\n'
        "    assert FiservGateway().charge()\n"
    )

    tests_for = get_tests_for(tmp_path, "app.cybersource.CybersourceApi._sign")

    assert tests_for == [
        {
            "test_file": "tests/test_fiserv.py",
            "confidence": "low",
            "evidence": ["indirect_call", "mocked"],
            "mocked": ["tests.test_fiserv.test_charge"],
        }
    ]


def test_get_tests_for_marks_a_file_whose_every_test_mocks_the_path_low_and_mocked(
    tmp_path,
):
    project_root = _mocked_checkout_project(tmp_path)
    (project_root / "tests" / "test_only_mocked.py").write_text(
        "from unittest.mock import patch\n"
        "\n"
        "from app.checkout import checkout\n"
        "\n"
        "\n"
        '@patch("app.payments._post")\n'
        "def test_checkout(post):\n"
        "    assert checkout()\n"
    )

    tests_for = get_tests_for(project_root, "app.payments._post")

    entry = next(t for t in tests_for if t["test_file"] == "tests/test_only_mocked.py")
    assert entry == {
        "test_file": "tests/test_only_mocked.py",
        "confidence": "low",
        "evidence": ["indirect_call", "mocked"],
        "mocked": ["tests.test_only_mocked.test_checkout"],
    }


def test_get_tests_for_sets_aside_a_direct_test_that_mocks_the_symbol_itself(tmp_path):
    project_root = _mocked_checkout_project(tmp_path)
    (project_root / "tests" / "test_payments.py").write_text(
        "from unittest.mock import patch\n"
        "\n"
        "from app.payments import process_payment\n"
        "\n"
        "\n"
        "def test_pays():\n"
        "    assert process_payment()\n"
        "\n"
        "\n"
        '@patch("app.payments.process_payment")\n'
        "def test_pays_mocked(pay):\n"
        "    assert process_payment()\n"
    )

    tests_for = get_tests_for(project_root, "app.payments.process_payment")

    assert tests_for == [
        {
            "test_file": "tests/test_payments.py",
            "confidence": "high",
            "evidence": ["symbol_reference"],
            "tests": ["tests.test_payments.test_pays"],
            "mocked": ["tests.test_payments.test_pays_mocked"],
        }
    ]


def test_get_tests_for_marks_a_direct_file_whose_every_test_mocks_the_symbol_low(
    tmp_path,
):
    project_root = _mocked_checkout_project(tmp_path)
    (project_root / "tests" / "test_payments.py").write_text(
        "from unittest.mock import patch\n"
        "\n"
        "from app.payments import process_payment\n"
        "\n"
        "\n"
        '@patch("app.payments.process_payment")\n'
        "def test_pays_mocked(pay):\n"
        "    assert process_payment()\n"
    )

    tests_for = get_tests_for(project_root, "app.payments.process_payment")

    assert tests_for == [
        {
            "test_file": "tests/test_payments.py",
            "confidence": "low",
            "evidence": ["symbol_reference", "mocked"],
            "mocked": ["tests.test_payments.test_pays_mocked"],
        }
    ]


def test_get_tests_for_caps_the_mocked_tests_it_names(tmp_path):
    project_root = _mocked_checkout_project(tmp_path)
    (project_root / "tests" / "test_payments.py").write_text(
        "from unittest.mock import patch\n\nfrom app.payments import process_payment\n\n\n"
        + "".join(
            f'@patch("app.payments.process_payment")\n'
            f"def test_mocked_{n}(pay):\n    assert process_payment()\n\n\n"
            for n in range(3)
        )
    )

    tests_for = get_tests_for(project_root, "app.payments.process_payment", limit=2)

    assert tests_for[0]["mocked"] == [
        "tests.test_payments.test_mocked_0",
        "tests.test_payments.test_mocked_1",
    ]
    assert tests_for[0]["mocked_total"] == 3
