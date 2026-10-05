from project_mcp.analyzers.python.mock_patches import (
    extract_fixture_patches,
    extract_mock_patches,
)


def test_extract_mock_patches_reads_a_patch_decorator_on_a_test():
    source = (
        "from unittest.mock import patch\n"
        "\n"
        "\n"
        '@patch("app.checkout.process_payment")\n'
        "def test_checkout(process_payment):\n"
        "    assert process_payment\n"
    )

    assert extract_mock_patches("tests/test_checkout.py", source) == [
        {
            "caller": "tests.test_checkout.test_checkout",
            "target": "app.checkout.process_payment",
        }
    ]


def test_extract_mock_patches_reads_patch_object_as_a_local_object_and_attribute():
    source = (
        "from app import payments\n"
        "from app.payments import Api\n"
        "\n"
        "\n"
        "def test_pays(mocker):\n"
        '    mocker.patch.object(Api, "_post")\n'
        '    with patch.object(payments.Api, "_sign"):\n'
        "        assert Api().process_payment()\n"
    )

    assert extract_mock_patches("tests/test_pay.py", source) == [
        {"caller": "tests.test_pay.test_pays", "object": "Api", "attribute": "_post"},
        {
            "caller": "tests.test_pay.test_pays",
            "object": "payments.Api",
            "attribute": "_sign",
        },
    ]


def test_extract_mock_patches_applies_a_class_decorator_to_each_test_method():
    source = (
        "from unittest import TestCase\n"
        "from unittest.mock import patch\n"
        "\n"
        "\n"
        '@patch("app.payments._post")\n'
        "class TestPay(TestCase):\n"
        "    def _helper(self):\n"
        "        return 1\n"
        "\n"
        "    def test_one(self, post):\n"
        "        assert post\n"
        "\n"
        "    def test_two(self, post):\n"
        "        assert post\n"
    )

    assert extract_mock_patches("tests/test_pay.py", source) == [
        {"caller": "tests.test_pay.TestPay.test_one", "target": "app.payments._post"},
        {"caller": "tests.test_pay.TestPay.test_two", "target": "app.payments._post"},
    ]


def test_extract_mock_patches_applies_a_patch_started_in_setup_to_each_test_method():
    source = (
        "from unittest import TestCase, mock\n"
        "\n"
        "\n"
        "class TestPay(TestCase):\n"
        "    def setUp(self):\n"
        '        mock.patch("app.payments._post").start()\n'
        "\n"
        "    def test_one(self):\n"
        "        assert True\n"
        "\n"
        "\n"
        "class TestRefund:\n"
        "    def setup_method(self):\n"
        '        mock.patch("app.payments._refund").start()\n'
        "\n"
        "    def test_refund(self):\n"
        "        assert True\n"
    )

    assert extract_mock_patches("tests/test_pay.py", source) == [
        {"caller": "tests.test_pay.TestPay.test_one", "target": "app.payments._post"},
        {
            "caller": "tests.test_pay.TestRefund.test_refund",
            "target": "app.payments._refund",
        },
    ]


def test_extract_mock_patches_applies_a_fixture_patch_to_each_test_requesting_it():
    source = (
        "import pytest\n"
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def paid(mocker):\n"
        '    return mocker.patch("app.payments._post")\n'
        "\n"
        "\n"
        "def test_paid(paid):\n"
        "    assert paid\n"
        "\n"
        "\n"
        "def test_unpaid():\n"
        "    assert True\n"
    )

    assert extract_mock_patches("tests/test_pay.py", source) == [
        {"caller": "tests.test_pay.test_paid", "target": "app.payments._post"},
    ]


def test_extract_mock_patches_applies_an_autouse_fixture_patch_to_each_test_in_its_scope():
    source = (
        "import pytest\n"
        "\n"
        "\n"
        "@pytest.fixture(autouse=True)\n"
        "def no_network(mocker):\n"
        '    mocker.patch("app.payments._post")\n'
        "\n"
        "\n"
        "def test_pay():\n"
        "    assert True\n"
        "\n"
        "\n"
        "class TestRefund:\n"
        "    @pytest.fixture(autouse=True)\n"
        "    def signed(self, mocker):\n"
        '        mocker.patch("app.payments._sign")\n'
        "\n"
        "    def test_refund(self):\n"
        "        assert True\n"
    )

    assert extract_mock_patches("tests/test_pay.py", source) == [
        {"caller": "tests.test_pay.test_pay", "target": "app.payments._post"},
        {"caller": "tests.test_pay.TestRefund.test_refund", "target": "app.payments._post"},
        {"caller": "tests.test_pay.TestRefund.test_refund", "target": "app.payments._sign"},
    ]


def test_extract_mock_patches_follows_a_fixture_requesting_a_patching_fixture():
    source = (
        "import pytest\n"
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def no_network(mocker):\n"
        '    mocker.patch("app.payments._post")\n'
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def gateway(no_network):\n"
        "    return object()\n"
        "\n"
        "\n"
        "def test_pay(gateway):\n"
        "    assert gateway\n"
    )

    assert extract_mock_patches("tests/test_pay.py", source) == [
        {"caller": "tests.test_pay.test_pay", "target": "app.payments._post"},
    ]


def test_extract_fixture_patches_names_the_patches_each_fixture_puts_in_force():
    source = (
        "import pytest\n"
        "\n"
        "\n"
        "@pytest.fixture(autouse=True)\n"
        "def no_network(mocker):\n"
        '    mocker.patch("app.payments._post")\n'
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def gateway(no_network, mocker):\n"
        '    mocker.patch.object(Gateway, "_sign")\n'
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def user():\n"
        "    return object()\n"
    )

    assert extract_fixture_patches("tests/conftest.py", source) == {
        "no_network": {"autouse": True, "patches": [{"target": "app.payments._post"}]},
        "gateway": {
            "autouse": False,
            "patches": [
                {"object": "Gateway", "attribute": "_sign"},
                {"target": "app.payments._post"},
            ],
        },
        "user": {"autouse": False, "patches": []},
    }


def test_extract_mock_patches_applies_patches_of_fixtures_defined_outside_the_file():
    source = (
        "import pytest\n"
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def paid_gateway(gateway):\n"
        "    return gateway\n"
        "\n"
        "\n"
        "def test_pay(paid_gateway):\n"
        "    assert paid_gateway\n"
        "\n"
        "\n"
        "def test_refund():\n"
        "    assert True\n"
    )
    outer_fixtures = {
        "no_network": {"autouse": True, "patches": [{"target": "app.payments._post"}]},
        "gateway": {"autouse": False, "patches": [{"symbol": "app.payments.Gateway._sign"}]},
    }

    assert extract_mock_patches("tests/test_pay.py", source, outer_fixtures) == [
        {"caller": "tests.test_pay.test_pay", "target": "app.payments._post"},
        {"caller": "tests.test_pay.test_pay", "symbol": "app.payments.Gateway._sign"},
        {"caller": "tests.test_pay.test_refund", "target": "app.payments._post"},
    ]
