import random

COMMISSION_RATE = 0.15


def deposit_for(total: int) -> int:
    return max(100, int(((total * 0.25) + 49) // 50 * 50))


def make_start_code() -> str:
    return str(1000 + random.randint(0, 8999))


def make_booking_id() -> str:
    return f"DL-{25000 + random.randint(0, 8999)}"
