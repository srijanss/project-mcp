"""Legacy checkout flow.

TODO: rewrite this module — it predates the Order/PaymentGateway split
and still does its own ad-hoc total calculation.
"""


def legacy_checkout(cart_items, tax_rate=0.0):
    # FIXME: duplicates shop.orders/shop.payments logic; kept for the
    # old mobile client which still posts to this entrypoint.
    subtotal = sum(item["price_cents"] for item in cart_items)
    return int(subtotal * (1 + tax_rate))
