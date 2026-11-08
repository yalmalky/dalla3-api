from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import models
from ..auth import get_current_user
from ..db import get_db
from ..reviewer_lane import apply_expert_onboarding
from ..schemas import ExpertProfileIn, ServiceIn
from ..serializers import expert_out, service_out

router = APIRouter(prefix="/me/expert", tags=["expert"])


@router.get("")
def my_expert(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    e = db.query(models.ExpertProfile).options(joinedload(models.ExpertProfile.services)).filter_by(user_id=user.id).first()
    if not e:
        return None
    data = expert_out(e)
    data["status"] = e.status
    data["services"] = [service_out(s) for s in e.services]
    return data


@router.put("")
def upsert_expert(body: ExpertProfileIn, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "expert":
        user.role = "expert"
    e = db.query(models.ExpertProfile).filter_by(user_id=user.id).first()
    if not e:
        e = models.ExpertProfile(user_id=user.id, display_name=body.display_name, is_test=bool(user.is_test))
        db.add(e)
        db.flush()
    e.display_name = body.display_name
    e.title = body.title
    e.bio = body.bio
    e.categories = body.categories
    e.districts = body.districts
    e.city = body.city
    e.modes = body.modes
    e.travel_fee = body.travel_fee
    e.years_exp = body.years_exp
    e.portfolio = body.portfolio
    e.hours = body.hours
    e.cover = body.cover
    e.tint = body.tint
    apply_expert_onboarding(user, e, body)
    if body.services:
        # replace services
        for s in list(e.services):
            db.delete(s)
        db.flush()
        for s in body.services:
            db.add(models.Service(
                expert_id=e.id,
                category=s.category,
                name=s.name,
                duration_min=s.duration_min,
                price=s.price,
                description=s.description,
            ))
    db.commit()
    db.refresh(e)
    e = (
        db.query(models.ExpertProfile)
        .options(joinedload(models.ExpertProfile.services), joinedload(models.ExpertProfile.user))
        .filter_by(id=e.id)
        .one()
    )
    data = expert_out(e)
    data["status"] = e.status
    data["services"] = [service_out(s) for s in e.services]
    return data


@router.put("/services")
def replace_services(services: list[ServiceIn] = Body(...), user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    e = db.query(models.ExpertProfile).filter_by(user_id=user.id).first()
    if not e:
        raise HTTPException(400, "كمّلي ملف الخبيرة أول")
    for s in list(e.services):
        db.delete(s)
    db.flush()
    for s in services:
        db.add(models.Service(expert_id=e.id, category=s.category, name=s.name, duration_min=s.duration_min, price=s.price, description=s.description))
    db.commit()
    rows = db.query(models.Service).filter_by(expert_id=e.id, active=True).all()
    return [service_out(s) for s in rows]


@router.put("/hours")
def update_hours(hours: dict = Body(...), user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    e = db.query(models.ExpertProfile).filter_by(user_id=user.id).first()
    if not e:
        raise HTTPException(400, "كمّلي ملف الخبيرة أول")
    e.hours = hours
    db.commit()
    return {"ok": True, "hours": e.hours}


@router.get("/earnings")
def earnings(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    e = db.query(models.ExpertProfile).filter_by(user_id=user.id).first()
    if not e:
        return {"escrow": 0, "available": 0, "lines": []}
    lines = db.query(models.PaymentLedger).filter_by(expert_id=e.id).order_by(models.PaymentLedger.created_at.desc()).limit(100).all()
    escrow = sum(l.amount for l in lines if l.kind == "escrow_hold") - sum(l.amount for l in lines if l.kind in ("escrow_release", "refund"))
    # net available from releases
    available = sum(l.amount for l in lines if l.kind == "escrow_release")
    # commissions tracked separately
    return {
        "escrow": max(0, escrow),
        "available": max(0, available),
        "lines": [
            {
                "id": l.id,
                "bookingId": l.booking_id,
                "kind": l.kind,
                "amount": l.amount,
                "note": l.note,
                "createdAt": l.created_at.isoformat() if l.created_at else "",
            }
            for l in lines
        ],
    }
