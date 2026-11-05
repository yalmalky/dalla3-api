from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..auth import get_current_user
from ..db import get_db
from ..schemas import AddressIn

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/profile")
def profile(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    addrs = db.query(models.Address).filter_by(user_id=user.id).all()
    if not addrs:
        a = models.Address(user_id=user.id, label="البيت", details=f"{user.city} — حي النرجس")
        db.add(a)
        db.commit()
        db.refresh(a)
        addrs = [a]
    return {
        "id": user.id,
        "name": user.name,
        "phone": user.phone or user.email,
        "city": user.city,
        "role": user.role,
        "email": user.email,
        "addresses": [
            {"id": a.id, "label": a.label, "details": a.details, "location": {"lat": a.lat, "lng": a.lng}}
            for a in addrs
        ],
    }


@router.post("/addresses")
def add_address(body: AddressIn, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = models.Address(user_id=user.id, label=body.label, details=body.details, lat=body.lat, lng=body.lng)
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"id": a.id, "label": a.label, "details": a.details, "location": {"lat": a.lat, "lng": a.lng}}


@router.get("/favorites")
def favorites(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [f.expert_id for f in db.query(models.Favorite).filter_by(user_id=user.id).all()]


@router.post("/favorites/{expert_id}")
def toggle_favorite(expert_id: str, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    existing = db.query(models.Favorite).filter_by(user_id=user.id, expert_id=expert_id).first()
    if existing:
        db.delete(existing)
    else:
        db.add(models.Favorite(user_id=user.id, expert_id=expert_id))
    db.commit()
    return [f.expert_id for f in db.query(models.Favorite).filter_by(user_id=user.id).all()]


@router.get("/notifications")
def notifications(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(models.Notification)
        .filter_by(user_id=user.id)
        .order_by(models.Notification.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": n.id,
            "title": n.title,
            "body": n.body,
            "kind": n.kind,
            "bookingId": n.booking_id,
            "read": n.read,
            "createdAt": n.created_at.isoformat() if n.created_at else "",
        }
        for n in rows
    ]


@router.post("/notifications/read")
def mark_read(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(models.Notification).filter_by(user_id=user.id, read=False).update({"read": True})
    db.commit()
    return {"ok": True}
