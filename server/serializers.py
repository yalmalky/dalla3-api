from math import cos, radians, sqrt

from . import models

CATEGORIES = [
    {"id": "makeup", "name": "مكياج", "icon": "brush", "tint": "--pink-50"},
    {"id": "hair", "name": "شعر", "icon": "scissors", "tint": "--lav-50"},
    {"id": "nails", "name": "أظافر", "icon": "gem", "tint": "--peach-50"},
    {"id": "skin", "name": "بشرة", "icon": "droplet", "tint": "--lav-50"},
    {"id": "henna", "name": "حناء", "icon": "leaf", "tint": "--sage-50"},
    {"id": "massage", "name": "مساج", "icon": "flower", "tint": "--mint-50"},
]


def rough_km(a_lat, a_lng, b_lat, b_lng) -> float:
    # cheap approx for Riyadh-scale distances
    dy = (a_lat - b_lat) * 111
    dx = (a_lng - b_lng) * 111 * cos(radians((a_lat + b_lat) / 2))
    return round(sqrt(dx * dx + dy * dy), 1)



STOCK_COVER = {
    "makeup": "makeup1",
    "hair": "hair1",
    "nails": "nails1",
    "skin": "skin1",
    "henna": "henna1",
    "massage": "massage1",
}
STOCK_HOST = "https://dalla3.onrender.com"


def _usable_cover(src: str | None) -> bool:
    if not src:
        return False
    s = src.strip()
    if not s:
        return False
    if s.startswith("data:") and len(s) < 200:
        return False
    return True


def cover_for(e: models.ExpertProfile) -> str:
    if _usable_cover(e.cover):
        return e.cover.strip()
    port = e.portfolio or []
    for item in port:
        if _usable_cover(item):
            return str(item).strip()
    cats = e.categories or ["makeup"]
    cat = cats[0] if cats else "makeup"
    name = STOCK_COVER.get(cat, "makeup1")
    # stable variety
    h = sum(ord(c) for c in (e.id or "")) % 3
    alts = {
        "makeup": ["makeup1", "makeup2", "skin1"],
        "hair": ["hair1", "hair2", "hair1"],
        "nails": ["nails1", "henna1", "nails1"],
        "skin": ["skin1", "massage1", "skin1"],
        "henna": ["henna1", "nails1", "henna1"],
        "massage": ["massage1", "skin1", "massage1"],
    }
    name = alts.get(cat, ["makeup1"])[h]
    return f"{STOCK_HOST}/img/{name}.webp"


def expert_out(e: models.ExpertProfile, origin=(24.7136, 46.6753)) -> dict:
    prices = [s.price for s in e.services if s.active]
    return {
        "id": e.id,
        "name": e.display_name,
        "title": e.title,
        "categories": e.categories or [],
        "district": (e.districts or ["الرياض"])[0],
        "city": e.city,
        "location": {"lat": e.lat, "lng": e.lng},
        "distanceKm": rough_km(origin[0], origin[1], e.lat, e.lng),
        "rating": e.rating or 5.0,
        "reviewsCount": e.reviews_count,
        "bookingsCount": e.bookings_count,
        "yearsExp": e.years_exp,
        "priceFrom": min(prices) if prices else 0,
        "modes": e.modes or ["home"],
        "travelFee": e.travel_fee,
        "nafathVerified": e.nafath_verified,
        "sponsored": e.sponsored,
        "nextAvailable": "اليوم",
        "cover": cover_for(e),
        "portfolio": e.portfolio or [],
        "bio": e.bio or "",
        "tint": e.tint or "lavender",
        "hours": e.hours or {},
        "userId": e.user_id,
    }


def service_out(s: models.Service) -> dict:
    return {
        "id": s.id,
        "expertId": s.expert_id,
        "category": s.category,
        "name": s.name,
        "durationMin": s.duration_min,
        "price": s.price,
        "description": s.description or "",
    }


def booking_out(b: models.Booking) -> dict:
    return {
        "id": b.id,
        "expertId": b.expert_id,
        "serviceIds": b.service_ids or [],
        "mode": b.mode,
        "date": b.date,
        "time": b.time,
        "address": b.address_json,
        "subtotal": b.subtotal,
        "travelFee": b.travel_fee,
        "total": b.total,
        "deposit": b.deposit,
        "remaining": b.remaining,
        "paymentMethod": b.payment_method,
        "status": b.status,
        "createdAt": b.created_at.isoformat() if b.created_at else "",
        "_platformCommission": b.platform_commission,
        "startCode": b.start_code,
        "customerName": b.customer_name,
        "expertName": b.expert_name,
        "serviceName": b.service_name,
        "rejectReason": b.reject_reason,
        "suggestedTime": b.suggested_time,
        "rating": b.rating,
        "ratingText": b.rating_text,
        "escrowReleased": b.escrow_released,
        "startedAt": b.started_at.isoformat() if b.started_at else None,
        "completedAt": b.completed_at.isoformat() if b.completed_at else None,
        "customerId": b.customer_id,
        "paymentProvider": b.payment_provider,
        "paymentRef": b.payment_ref,
    }


def notify(db, user_id: str, title: str, body: str, booking_id: str | None = None, kind: str = "booking"):
    n = models.Notification(user_id=user_id, title=title, body=body, booking_id=booking_id, kind=kind)
    db.add(n)
