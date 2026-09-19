from shop.orders import Order, cancel_order


def test_cancel_order_marks_cancelled():
    order = Order(id="1", status="placed", total_cents=1000)
    cancel_order(order)
    assert order.status == "cancelled"


def test_cancel_order_rejects_shipped():
    order = Order(id="1", status="shipped", total_cents=1000)
    try:
        cancel_order(order)
        assert False, "expected ValueError"
    except ValueError:
        pass
