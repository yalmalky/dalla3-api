from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .. import models
from ..auth import get_current_user
from ..config import get_settings
from ..db import get_db
from ..money import BNPL_SURCHARGE_RATE, bnpl_surcharge_for, deposit_for, is_bnpl, make_booking_id, make_start_code
from ..payments import get_payment_provider
from ..reviewer_lane import ACTIVE_BOOKING_STATUSES, can_discover_expert, pair_in_reviewer_lane
from ..schemas import BookingIn, RateIn, RejectIn, StartCodeIn
from ..serializers import booking_out, notify

router = APIRouter(prefix="/bookings", tags=["bookings"])


def _quote(expert: models.ExpertProfile, service_ids: list[str], mode: str):
    services = [s for s in expert.services if s.id in service_ids and s.active]
    if not services:
        raise HTTPException(400, "اختاري خدمة")
    subtotal = sum(s.price for s in services)
    travel = expert.travel_fee if mode == "home" else 0
    total = subtotal + travel
    deposit = deposit_for(total) if subtotal else 0
    deposit = min(deposit, total)
    return {
        "subtotal": subtotal,
        "travelFee": travel,
        "total": total,
        "deposit": deposit,
        "remaining": total - deposit,
        "bnplSurchargeRate": BNPL_SURCHARGE_RATE,
        "services": services,
    }


def _load_expert(db: Session, expert_id: str) -> models.ExpertProfile | None:
    return (
        db.query(models.ExpertProfile)
        .options(joinedload(models.ExpertProfile.services), joinedload(models.ExpertProfile.user))
        .filter_by(id=expert_id)
        .first()
    )


def _provider_for(booking: models.Booking):
    # Lane bookings stay on the simulator even if PAYMENT_PROVIDER later changes, or the row was edited.
    if booking.reviewer_lane:
        return get_payment_provider("mock")
    return get_payment_provider(booking.payment_provider)


@router.post("/quote")
def quote(body: BookingIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    e = _load_expert(db, body.expert_id)
    if e is None or not can_discover_expert(user, e):
        raise HTTPException(404, "الخبيرة غير موجودة")
    q = _quote(e, body.service_ids, body.mode)
    q.pop("services", None)
    return q


@router.post("")
def create_booking(body: BookingIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    e = _load_expert(db, body.expert_id)
    if e is None or not can_discover_expert(user, e):
        raise HTTPException(404, "الخبيرة غير موجودة")
    lane = pair_in_reviewer_lane(user, e)
    clash = db.query(models.Booking).filter(
        models.Booking.expert_id == e.id,
        models.Booking.date == body.date,
        models.Booking.time == body.time,
        models.Booking.status.in_(ACTIVE_BOOKING_STATUSES),
    ).first()
    if clash:
        raise HTTPException(409, "هذا الموعد محجوز — اختاري وقت ثاني")
    q = _quote(e, body.service_ids, body.mode)
    bnpl = is_bnpl(body.payment_method)
    # Backend computes surcharge — never trust a client-supplied fee.
    surcharge = bnpl_surcharge_for(q["total"], body.payment_method)
    deposit = (q["total"] + surcharge) if bnpl else float(q["deposit"])
    remaining = 0.0 if bnpl else float(q["remaining"])
    commission = round(q["subtotal"] * get_settings().commission_rate)
    address = None
    if body.address_id:
        a = db.query(models.Address).filter_by(id=body.address_id, user_id=user.id).first()
        if a:
            address = {"id": a.id, "label": a.label, "details": a.details, "location": {"lat": a.lat, "lng": a.lng}}
    elif user.addresses:
        a = user.addresses[0]
        address = {"id": a.id, "label": a.label, "details": a.details, "location": {"lat": a.lat, "lng": a.lng}}

    bid = make_booking_id()
    while db.get(models.Booking, bid):
        bid = make_booking_id()

    # Resolve the provider before claiming the slot so a missing live provider
    # does not hold the clock time. The unique index is claimed before any hold,
    # so a concurrent loser does not create a payment.
    provider = get_payment_provider("mock") if lane else get_payment_provider()
    b = models.Booking(
        id=bid,
        customer_id=user.id,
        expert_id=e.id,
        service_ids=body.service_ids,
        mode=body.mode,
        date=body.date,
        time=body.time,
        address_json=address,
        subtotal=q["subtotal"],
        travel_fee=q["travelFee"],
        total=q["total"],
        deposit=deposit,
        remaining=remaining,
        bnpl_surcharge=surcharge,
        payment_method=body.payment_method,
        status="pending_accept",
        platform_commission=commission,
        start_code=make_start_code(),
        customer_name=user.name,
        expert_name=e.display_name,
        service_name=" + ".join(s.name for s in q["services"]),
        payment_provider=provider.name,
        payment_ref=None,
        reviewer_lane=lane,
    )
    db.add(b)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "هذا الموعد محجوز — اختاري وقت ثاني")
    pay = provider.hold_escrow(amount=deposit, booking_id=bid, customer_id=user.id)
    if not pay.ok:
        db.rollback()
        raise HTTPException(402, pay.message or "فشل الدفع")
    b.payment_provider = pay.provider
    b.payment_ref = pay.ref
    db.add(models.PaymentLedger(
        booking_id=bid, expert_id=e.id, customer_id=user.id,
        kind="escrow_hold", amount=deposit, provider=pay.provider, provider_ref=pay.ref,
        note="عربون محجوز — بانتظار قبول الخبيرة",
    ))
    if surcharge:
        db.add(models.PaymentLedger(
            booking_id=bid, expert_id=e.id, customer_id=user.id,
            kind="bnpl_surcharge", amount=surcharge, provider=pay.provider, provider_ref=pay.ref,
            note="رسوم خدمة التقسيط 2.5٪ للمنصة (لا تخصم من حصة الخبيرة)",
        ))
    notify(db, e.user_id, "طلب حجز جديد", f"{user.name} طلبت {b.service_name}", booking_id=bid)
    notify(db, user.id, "طلبك انرسل", f"بانتظار قبول {e.display_name}", booking_id=bid)
    e.bookings_count = (e.bookings_count or 0) + 1
    db.commit()
    db.refresh(b)
    return booking_out(b)


@router.get("")
def list_bookings(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(models.Booking)
    if user.role == "expert" and user.expert_profile:
        q = q.filter(models.Booking.expert_id == user.expert_profile.id)
    else:
        q = q.filter(models.Booking.customer_id == user.id)
    rows = q.order_by(models.Booking.created_at.desc()).all()
    return [booking_out(b) for b in rows]


@router.get("/{booking_id}")
def get_booking(booking_id: str, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.get(models.Booking, booking_id)
    if not b:
        raise HTTPException(404, "الحجز غير موجود")
    if b.customer_id != user.id and not (user.expert_profile and user.expert_profile.id == b.expert_id):
        raise HTTPException(403, "ما عندك صلاحية")
    return booking_out(b)


@router.post("/{booking_id}/accept")
def accept(booking_id: str, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.get(models.Booking, booking_id)
    if not b or not user.expert_profile or b.expert_id != user.expert_profile.id:
        raise HTTPException(403, "مو حجزك")
    if b.status != "pending_accept":
        raise HTTPException(400, "الحجز مو بانتظار القبول")
    b.status = "confirmed"
    notify(db, b.customer_id, "تم قبول حجزك", f"{b.expert_name} قبلت الطلب", booking_id=b.id)
    db.commit()
    db.refresh(b)
    return booking_out(b)


@router.post("/{booking_id}/reject")
def reject(booking_id: str, body: RejectIn, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.get(models.Booking, booking_id)
    if not b or not user.expert_profile or b.expert_id != user.expert_profile.id:
        raise HTTPException(403, "مو حجزك")
    if b.status != "pending_accept":
        raise HTTPException(400, "الحجز مو بانتظار القبول")
    b.status = "rejected"
    b.reject_reason = body.reason
    b.suggested_time = body.suggested_time
    provider = _provider_for(b)
    ref = provider.refund(amount=b.deposit, booking_id=b.id, reason=body.reason)
    db.add(models.PaymentLedger(
        booking_id=b.id, expert_id=b.expert_id, customer_id=b.customer_id,
        kind="refund", amount=b.deposit, provider=ref.provider, provider_ref=ref.ref,
        note=f"استرجاع بعد الرفض: {body.reason}",
    ))
    notify(db, b.customer_id, "تم رفض الحجز", body.reason, booking_id=b.id)
    db.commit()
    db.refresh(b)
    return booking_out(b)


@router.post("/{booking_id}/cancel")
def cancel_by_customer(booking_id: str, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Customer cancellation, only where the published rule already applies: free with a full refund while the
    expert hasn't accepted yet, or more than 24 h before the appointment (Riyadh time). Late cancellations
    (12-24 h / <12 h / no-show fees) wait for the owner's approval of the cancellation policy -> support."""
    from datetime import datetime, timedelta, timezone as _tz
    b = db.get(models.Booking, booking_id)
    if not b or b.customer_id != user.id:
        raise HTTPException(403, "مو حجزك")
    if b.status not in ("pending_accept", "confirmed"):
        raise HTTPException(400, "ما يمكن إلغاء هالحجز")
    riyadh = _tz(timedelta(hours=3))
    try:
        appt = datetime.strptime(f"{b.date} {b.time}", "%Y-%m-%d %H:%M").replace(tzinfo=riyadh)
    except ValueError:
        appt = None
    if b.status == "confirmed" and (appt is None or appt - datetime.now(riyadh) < timedelta(hours=24)):
        raise HTTPException(400, "الإلغاء المجاني متاح قبل الموعد بـ24 ساعة — تواصلي مع الدعم للإلغاء المتأخر")
    b.status = "cancelled"
    provider = _provider_for(b)
    ref = provider.refund(amount=b.deposit, booking_id=b.id, reason="customer_cancel")
    db.add(models.PaymentLedger(
        booking_id=b.id, expert_id=b.expert_id, customer_id=b.customer_id,
        kind="refund", amount=b.deposit, provider=ref.provider, provider_ref=ref.ref,
        note="استرجاع كامل: إلغاء العميلة (مجاني)",
    ))
    ex = db.get(models.ExpertProfile, b.expert_id)
    if ex:
        notify(db, ex.user_id, "تم إلغاء الحجز", f"العميلة ألغت حجز {b.date} {b.time}", booking_id=b.id)
    db.commit()
    db.refresh(b)
    return booking_out(b)


@router.post("/{booking_id}/start")
def start(booking_id: str, body: StartCodeIn, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.get(models.Booking, booking_id)
    if not b or not user.expert_profile or b.expert_id != user.expert_profile.id:
        raise HTTPException(403, "مو حجزك")
    if b.status not in ("confirmed", "on_the_way", "arrived"):
        raise HTTPException(400, "الحجز مو جاهز للبدء")
    if body.code.strip() != b.start_code:
        raise HTTPException(400, "كود البدء غلط")
    from datetime import datetime, timezone
    b.status = "in_progress"
    b.started_at = datetime.now(timezone.utc)
    b.escrow_released = True
    provider = _provider_for(b)
    rel = provider.release_escrow(amount=b.subtotal, booking_id=b.id, expert_id=b.expert_id, commission=b.platform_commission)
    db.add(models.PaymentLedger(
        booking_id=b.id, expert_id=b.expert_id, customer_id=b.customer_id,
        kind="escrow_release", amount=rel.amount, provider=rel.provider, provider_ref=rel.ref,
        note=rel.message,
    ))
    db.add(models.PaymentLedger(
        booking_id=b.id, expert_id=b.expert_id, customer_id=b.customer_id,
        kind="commission", amount=b.platform_commission, provider=rel.provider, provider_ref=rel.ref,
        note="عمولة المنصة ١٥٪",
    ))
    notify(db, b.customer_id, "الجلسة بدأت", "تم التحقق من كود البدء", booking_id=b.id)
    db.commit()
    db.refresh(b)
    return booking_out(b)


@router.post("/{booking_id}/complete")
def complete(booking_id: str, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.get(models.Booking, booking_id)
    if not b:
        raise HTTPException(404, "الحجز غير موجود")
    is_expert = user.expert_profile and user.expert_profile.id == b.expert_id
    is_customer = user.id == b.customer_id
    if not (is_expert or is_customer):
        raise HTTPException(403, "ما عندك صلاحية")
    from datetime import datetime, timezone
    b.status = "completed"
    b.completed_at = datetime.now(timezone.utc)
    notify(db, b.customer_id if is_expert else (user.expert_profile.user_id if user.expert_profile else b.customer_id),
           "اكتملت الخدمة", "قيّمي التجربة", booking_id=b.id)
    db.commit()
    db.refresh(b)
    return booking_out(b)


@router.post("/{booking_id}/rate")
def rate(booking_id: str, body: RateIn, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.get(models.Booking, booking_id)
    if not b or b.customer_id != user.id:
        raise HTTPException(403, "مو حجزك")
    from datetime import datetime, timezone
    b.rating = body.rating
    b.rating_text = body.text
    b.status = "completed"
    b.completed_at = b.completed_at or datetime.now(timezone.utc)
    db.add(models.Review(expert_id=b.expert_id, booking_id=b.id, author=user.name, rating=body.rating, text=body.text))
    e = db.get(models.ExpertProfile, b.expert_id)
    if e:
        n = e.reviews_count or 0
        e.rating = round(((e.rating or 5) * n + body.rating) / (n + 1), 2)
        e.reviews_count = n + 1
    db.commit()
    db.refresh(b)
    return booking_out(b)
