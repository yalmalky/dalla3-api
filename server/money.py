import random

COMMISSION_RATE = 0.15
BNPL_SURCHARGE_RATE = 0.025  # platform fee when customer picks Tabby/Tamara
BNPL_METHODS = frozenset({"tabby", "tamara"})


def deposit_for(total: int) -> int:
    return max(100, int(((total * 0.25) + 49) // 50 * 50))


def is_bnpl(method: str) -> bool:
    return (method or "").lower() in BNPL_METHODS


def bnpl_surcharge_for(total: int | float, method: str) -> float:
    """2.5% of full order (services + travel/VAT-inclusive total). Platform only; never reduces expert payout."""
    if not is_bnpl(method):
        return 0.0
    return round(float(total) * BNPL_SURCHARGE_RATE, 2)


def make_start_code() -> str:
    return str(1000 + random.randint(0, 8999))


def make_booking_id() -> str:
    return f"DL-{25000 + random.randint(0, 8999)}"
