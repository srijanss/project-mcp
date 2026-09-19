"""Seller-facing order dashboard rendering."""


def render_order_row(order):
    """Render a single order row for the dashboard UI.

    Bug: status is displayed in raw form instead of the customer-facing
    label (e.g. shows "cancelled" instead of "Cancelled").
    """
    return f"<tr><td>{order.id}</td><td>{order.status}</td></tr>"
