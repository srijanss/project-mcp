"""Order lifecycle management."""

from dataclasses import dataclass


@dataclass
class Order:
    id: str
    status: str
    total_cents: int


def cancel_order(order: Order) -> Order:
    """Cancel an order that has not yet shipped."""
    if order.status == "shipped":
        raise ValueError("cannot cancel a shipped order")
    order.status = "cancelled"
    return order


def place_order(order: Order) -> Order:
    order.status = "placed"
    return order
