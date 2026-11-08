from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from .. import models
from ..auth import get_optional_user
from ..db import get_db
from ..reviewer_lane import ACTIVE_BOOKING_STATUSES, can_discover_expert
from ..seed import ensure_promos
from ..serializers import CATEGORIES, expert_out, service_out

# Demo promos with no backing logic (e.g. WELCOME code is not applied at checkout) stay hidden.
HIDDEN_PROMOS = {"pr_welcome"}

router = APIRouter(tags=["catalog"])


@router.get("/categories")
def categories():
    return CATEGORIES


@router.get("/promos")
def promos(db: Session = Depends(get_db), user: models.User | None = Depends(get_optional_user)):
    ensure_promos(db)
    rows = []
    for p in db.query(models.Promo).all():
        if p.id in HIDDEN_PROMOS:
            continue
        if p.expert_id:
            expert = db.query(models.ExpertProfile).options(joinedload(models.ExpertProfile.user)).filter_by(id=p.expert_id).first()
            if not can_discover_expert(user, expert):
                continue
        rows.append(p)
    return [
        {
            "id": p.id,
            "title": p.title,
            "subtitle": p.subtitle,
            "cta": p.cta,
            "code": p.code,
            "badge": p.badge,
            "theme": p.theme,
            "sponsored": p.sponsored,
            "expertId": p.expert_id,
        }
        for p in rows
    ]


@router.get("/experts")
def list_experts(
    category: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_optional_user),
):
    rows = (
        db.query(models.ExpertProfile)
        .options(joinedload(models.ExpertProfile.services), joinedload(models.ExpertProfile.user))
        .filter(models.ExpertProfile.status == "approved")
        .all()
    )
    # is_test does not widen visibility. Reviewers see only the reviewer lane.
    deduped = []
    seen: set[str] = set()
    for e in rows:
        if e.id in seen:
            continue
        seen.add(e.id)
        deduped.append(e)
    rows = [e for e in deduped if can_discover_expert(user, e)]
    out = []
    for e in rows:
        if category and category != "all" and category not in (e.categories or []):
            continue
        if q:
            blob = " ".join([e.display_name, e.title, e.bio or "", " ".join(e.districts or [])])
            if q not in blob and not any(q in s.name for s in e.services):
                continue
        out.append(expert_out(e))
    out.sort(key=lambda x: (-int(x["sponsored"]), x["distanceKm"]))
    return out


def _visible_expert(expert_id: str, db: Session, user: models.User | None) -> models.ExpertProfile:
    e = (
        db.query(models.ExpertProfile)
        .options(joinedload(models.ExpertProfile.services), joinedload(models.ExpertProfile.user))
        .filter_by(id=expert_id)
        .first()
    )
    if not can_discover_expert(user, e):
        raise HTTPException(404, "الخبيرة غير موجودة")
    return e


@router.get("/experts/{expert_id}")
def get_expert(expert_id: str, db: Session = Depends(get_db), user: models.User | None = Depends(get_optional_user)):
    return expert_out(_visible_expert(expert_id, db, user))


@router.get("/experts/{expert_id}/services")
def list_services(expert_id: str, db: Session = Depends(get_db), user: models.User | None = Depends(get_optional_user)):
    e = _visible_expert(expert_id, db, user)
    return [service_out(s) for s in e.services if s.active]


@router.get("/experts/{expert_id}/reviews")
def list_reviews(expert_id: str, db: Session = Depends(get_db), user: models.User | None = Depends(get_optional_user)):
    _visible_expert(expert_id, db, user)
    rows = db.query(models.Review).filter_by(expert_id=expert_id).order_by(models.Review.created_at.desc()).limit(50).all()
    return [
        {
            "id": r.id,
            "expertId": r.expert_id,
            "author": r.author,
            "rating": r.rating,
            "text": r.text,
            "date": r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]


@router.get("/experts/{expert_id}/slots")
def slots(expert_id: str, date: str, db: Session = Depends(get_db), user: models.User | None = Depends(get_optional_user)):
    _visible_expert(expert_id, db, user)
    times = ["14:00", "15:30", "17:00", "18:30", "20:00", "21:30"]
    taken = {
        b.time
        for b in db.query(models.Booking).filter(
            models.Booking.expert_id == expert_id,
            models.Booking.date == date,
            models.Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
    }
    seed = sum(ord(c) for c in expert_id + date)
    return [{"time": t, "available": t not in taken and (seed + i * 7) % 5 != 0} for i, t in enumerate(times)]
