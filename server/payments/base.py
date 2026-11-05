from dataclasses import dataclass
from typing import Protocol


@dataclass
class PaymentResult:
    ok: bool
    provider: str
    ref: str
    amount: int
    currency: str = "SAR"
    message: str = ""


class PaymentProvider(Protocol):
    name: str

    def hold_escrow(self, *, amount: int, booking_id: str, customer_id: str, meta: dict | None = None) -> PaymentResult: ...
    def release_escrow(self, *, amount: int, booking_id: str, expert_id: str, commission: int, meta: dict | None = None) -> PaymentResult: ...
    def refund(self, *, amount: int, booking_id: str, reason: str = "") -> PaymentResult: ...
