from project_mcp.analyzers.frameworks.django_urls import (
    extract_url_patterns,
    extract_url_reverses,
)


def test_extract_url_patterns_reads_app_name_and_named_views():
    source = (
        "from django.urls import path\n"
        "\n"
        "from . import views\n"
        "from .views import receipt\n"
        "\n"
        'app_name = "checkout"\n'
        "\n"
        "urlpatterns = [\n"
        '    path("card/", views.CardPayment.as_view(), name="card-payment"),\n'
        '    path("receipt/", receipt, name="receipt"),\n'
        '    path("health/", views.health),\n'
        "]\n"
    )

    assert extract_url_patterns(source) == {
        "app_name": "checkout",
        "patterns": [
            {"name": "card-payment", "view": "views.CardPayment"},
            {"name": "receipt", "view": "receipt"},
        ],
        "includes": [],
    }


def test_extract_url_patterns_reads_included_modules_and_their_namespaces():
    source = (
        "from django.urls import include, path\n"
        "\n"
        "urlpatterns = [\n"
        '    path("pay/", include("shop.checkout.urls", namespace="pay")),\n'
        '    path("cart/", include(("shop.cart.urls", "cart"))),\n'
        '    path("extra/", include("shop.extra.urls")),\n'
        '    path("api/", include(router.urls)),\n'
        "]\n"
    )

    assert extract_url_patterns(source)["includes"] == [
        {"module": "shop.checkout.urls", "app_name": None, "namespace": "pay"},
        {"module": "shop.cart.urls", "app_name": "cart", "namespace": None},
        {"module": "shop.extra.urls", "app_name": None, "namespace": None},
    ]


def test_extract_url_reverses_names_the_function_reversing_each_url():
    source = (
        "from django.urls import reverse, reverse_lazy\n"
        "\n"
        "\n"
        "class TestCardPayment:\n"
        "    def test_shows_the_form(self, client):\n"
        '        response = client.get(reverse("checkout:card-payment"))\n'
        "        assert response.status_code == 200\n"
        "\n"
        "\n"
        "def test_receipt(client):\n"
        '    assert client.get(reverse_lazy("checkout:receipt", args=[1]))\n'
        "\n"
        "\n"
        "def test_dynamic(client, name):\n"
        "    assert client.get(reverse(name))\n"
    )

    assert extract_url_reverses("shop/tests/test_views.py", source) == [
        {
            "caller": "shop.tests.test_views.TestCardPayment.test_shows_the_form",
            "url_name": "checkout:card-payment",
        },
        {"caller": "shop.tests.test_views.test_receipt", "url_name": "checkout:receipt"},
    ]


def test_extract_url_patterns_reads_a_view_passed_by_keyword():
    source = (
        "from django.urls import path\n"
        "\n"
        "from . import views\n"
        "\n"
        "urlpatterns = [\n"
        '    path("card/", view=views.CardPayment.as_view(), name="card-payment"),\n'
        "]\n"
    )

    assert extract_url_patterns(source)["patterns"] == [
        {"name": "card-payment", "view": "views.CardPayment"}
    ]


def test_extract_url_reverses_reads_a_viewname_passed_by_keyword():
    source = (
        "from django.urls import reverse\n"
        "\n"
        "\n"
        "def test_shows_the_form(client):\n"
        '    assert client.get(reverse(viewname="checkout:card-payment"))\n'
    )

    assert extract_url_reverses("tests/test_views.py", source) == [
        {
            "caller": "tests.test_views.test_shows_the_form",
            "url_name": "checkout:card-payment",
        }
    ]


def test_extract_url_reverses_leaves_out_a_reverse_no_request_is_made_to():
    source = (
        "from django.urls import reverse\n"
        "\n"
        "\n"
        "def test_url_is_stable():\n"
        '    assert reverse("checkout:card-payment") == "/card/"\n'
    )

    assert extract_url_reverses("tests/test_views.py", source) == []


def test_extract_url_reverses_follows_a_reversed_url_through_a_variable():
    source = (
        "from django.urls import reverse\n"
        "\n"
        "\n"
        "def test_shows_the_form(client):\n"
        '    url = reverse("checkout:card-payment")\n'
        '    assert client.get(f"{url}?step=2")\n'
        "\n"
        "\n"
        "def test_url_is_stable():\n"
        '    url = reverse("checkout:receipt")\n'
        '    assert url == "/receipt/"\n'
    )

    assert extract_url_reverses("tests/test_views.py", source) == [
        {
            "caller": "tests.test_views.test_shows_the_form",
            "url_name": "checkout:card-payment",
        }
    ]


def test_extract_url_reverses_follows_a_url_a_test_class_reversed_onto_self():
    source = (
        "from django.test import TestCase\n"
        "from django.urls import reverse, reverse_lazy\n"
        "\n"
        "\n"
        "class TestCardPayment(TestCase):\n"
        '    receipt_url = reverse_lazy("checkout:receipt")\n'
        "\n"
        "    def test_shows_the_form(self):\n"
        "        assert self.client.get(self.url)\n"
        "\n"
        "    def test_shows_the_receipt(self):\n"
        "        assert self.client.get(self.receipt_url)\n"
        "\n"
        "    def setUp(self):\n"
        '        self.url = reverse("checkout:card-payment")\n'
    )

    assert extract_url_reverses("tests/test_views.py", source) == [
        {
            "caller": "tests.test_views.TestCardPayment.test_shows_the_form",
            "url_name": "checkout:card-payment",
        },
        {
            "caller": "tests.test_views.TestCardPayment.test_shows_the_receipt",
            "url_name": "checkout:receipt",
        },
    ]


def test_extract_url_reverses_follows_a_url_reversed_at_module_level():
    source = (
        "from django.urls import reverse\n"
        "\n"
        'URL = reverse("checkout:card-payment")\n'
        "\n"
        "\n"
        "def test_shows_the_form(client):\n"
        "    assert client.get(URL)\n"
    )

    assert extract_url_reverses("tests/test_views.py", source) == [
        {
            "caller": "tests.test_views.test_shows_the_form",
            "url_name": "checkout:card-payment",
        }
    ]
