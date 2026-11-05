from math import cos, radians, sqrt

from . import models

CATEGORIES = [
    {"id": "makeup", "name": "مكياج", "icon": "Sparkles", "tint": "lavender"},
    {"id": "hair", "name": "شعر", "icon": "Scissors", "tint": "pink"},
    {"id": "nails", "name": "أظافر", "icon": "Hand", "tint": "mint"},
    {"id": "skin", "name": "بشرة", "icon": "Droplets", "tint": "lavender"},
    {"id": "henna", "name": "حناء", "icon": "Flower2", "tint": "pink"},
    {"id": "massage", "name": "مساج", "icon": "Heart", "tint": "mint"},
]


def rough_km(a_lat, a_lng, b_lat, b_lng) -> float:
    # cheap approx for Riyadh-scale distances
    dy = (a_lat - b_lat) * 111
    dx = (a_lng - b_lng) * 111 * cos(radians((a_lat + b_lat) / 2))
    return round(sqrt(dx * dx + dy * dy), 1)


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
        "cover": e.cover or "",
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
