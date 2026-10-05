from project_mcp.analyzers.python.mock_patches import extract_mock_patches


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
