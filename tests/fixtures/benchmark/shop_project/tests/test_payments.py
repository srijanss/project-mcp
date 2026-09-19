from shop.payments import PaymentGateway, capture_payment


def test_capture_payment_charges_gateway():
    gateway = PaymentGateway(api_key="test")
    result = capture_payment(gateway, 500)
    assert result == "charge:500"
