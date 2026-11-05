from dataclasses import dataclass
from typing import Protocol


@dataclass
class PaymentResult:
    ok: bool
    provider: str
    ref: str
    amount: float
    currency: str = "SAR"
    message: str = ""


class PaymentProvider(Protocol):
    name: str

    def hold_escrow(self, *, amount: float, booking_id: str, customer_id: str, meta: dict | None = None) -> PaymentResult: ...
    def release_escrow(self, *, amount: float, booking_id: str, expert_id: str, commission: float, meta: dict | None = None) -> PaymentResult: ...
    def refund(self, *, amount: float, booking_id: str, reason: str = "") -> PaymentResult: ...
