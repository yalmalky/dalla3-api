from .base import PaymentProvider, PaymentResult
from .mock import MockPaymentProvider


def get_payment_provider(name: str | None = None) -> PaymentProvider:
    from ..config import get_settings
    n = (name or get_settings().payment_provider or "mock").lower()
    if n == "mock":
        return MockPaymentProvider()
    if n == "moyasar":
        # Pluggable later — raise until keys exist
        raise RuntimeError("Moyasar provider not configured yet")
    return MockPaymentProvider()
