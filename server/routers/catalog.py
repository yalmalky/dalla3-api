from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from .. import models
from ..auth import get_optional_user
from ..db import get_db
from ..seed import ensure_promos
from ..serializers import CATEGORIES, expert_out, service_out

router = APIRouter(tags=["catalog"])


@router.get("/categories")
def categories():
    return CATEGORIES


@router.get("/promos")
def promos(db: Session = Depends(get_db)):
    ensure_promos(db)
    rows = db.query(models.Promo).all()
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
        .options(joinedload(models.ExpertProfile.services))
        .filter(models.ExpertProfile.status == "approved")
        .all()
    )
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


@router.get("/experts/{expert_id}")
def get_expert(expert_id: str, db: Session = Depends(get_db)):
    e = db.query(models.ExpertProfile).options(joinedload(models.ExpertProfile.services)).filter_by(id=expert_id).first()
    if not e:
        return None
    return expert_out(e)


@router.get("/experts/{expert_id}/services")
def list_services(expert_id: str, db: Session = Depends(get_db)):
    rows = db.query(models.Service).filter_by(expert_id=expert_id, active=True).all()
    return [service_out(s) for s in rows]


@router.get("/experts/{expert_id}/reviews")
def list_reviews(expert_id: str, db: Session = Depends(get_db)):
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
def slots(expert_id: str, date: str, db: Session = Depends(get_db)):
    times = ["14:00", "15:30", "17:00", "18:30", "20:00", "21:30"]
    taken = {
        b.time
        for b in db.query(models.Booking).filter(
            models.Booking.expert_id == expert_id,
            models.Booking.date == date,
            models.Booking.status.in_(["pending_accept", "confirmed", "on_the_way", "arrived", "in_progress"]),
        )
    }
    seed = sum(ord(c) for c in expert_id + date)
    return [{"time": t, "available": t not in taken and (seed + i * 7) % 5 != 0} for i, t in enumerate(times)]
