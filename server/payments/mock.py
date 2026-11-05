import uuid

from .base import PaymentResult


class MockPaymentProvider:
    """Family-test provider: simulates Mada/Apple Pay / BNPL escrow without real charges.
    Swap to Moyasar by setting PAYMENT_PROVIDER=moyasar once merchant keys exist.
    """

    name = "mock"

    def hold_escrow(self, *, amount: float, booking_id: str, customer_id: str, meta: dict | None = None) -> PaymentResult:
        return PaymentResult(ok=True, provider=self.name, ref=f"mock_hold_{booking_id}_{uuid.uuid4().hex[:6]}", amount=amount, message="عربون محجوز (تجريبي)")

    def release_escrow(self, *, amount: float, booking_id: str, expert_id: str, commission: float, meta: dict | None = None) -> PaymentResult:
        net = amount - commission
        return PaymentResult(ok=True, provider=self.name, ref=f"mock_rel_{booking_id}_{uuid.uuid4().hex[:6]}", amount=net, message=f"انفك الضمان · صافي {net} · عمولة {commission}")

    def refund(self, *, amount: float, booking_id: str, reason: str = "") -> PaymentResult:
        return PaymentResult(ok=True, provider=self.name, ref=f"mock_ref_{booking_id}_{uuid.uuid4().hex[:6]}", amount=amount, message=reason or "استرجاع")
