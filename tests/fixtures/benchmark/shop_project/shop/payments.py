"""Payment capture against the upstream payment gateway."""

from dataclasses import dataclass


@dataclass
class PaymentGateway:
    api_key: str

    def charge(self, amount_cents: int) -> str:
        return f"charge:{amount_cents}"


def capture_payment(gateway: PaymentGateway, amount_cents: int) -> str:
    """Capture a previously authorized payment."""
    return gateway.charge(amount_cents)
