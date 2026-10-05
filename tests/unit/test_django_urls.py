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
