"""Admin: list / hide / unhide test accounts. Enabled only when env ADMIN_TOKEN is set; send it as X-Admin-Token."""
import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..reviewer_lane import is_designated_email

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(x_admin_token: str | None = Header(default=None)):
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected or not x_admin_token or not hmac.compare_digest(expected, x_admin_token):
        raise HTTPException(404, "Not Found")


class FlagIn(BaseModel):
    hidden: bool
    expert_ids: list[str] = []
    user_ids: list[str] = []
    emails: list[str] = []


def _expert_row(e: models.ExpertProfile):
    return {"id": e.id, "name": e.display_name, "email": e.user.email if e.user else None, "status": e.status,
            "hidden": bool(e.is_test), "createdAt": e.created_at.isoformat() if e.created_at else None}


@router.get("/test-accounts", dependencies=[Depends(require_admin)])
def list_accounts(db: Session = Depends(get_db)):
    experts = db.query(models.ExpertProfile).order_by(models.ExpertProfile.created_at).all()
    users = db.query(models.User).order_by(models.User.created_at).all()
    return {
        "experts": [_expert_row(e) for e in experts],
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "role": u.role,
                "hidden": bool(u.is_test),
                "reviewerLane": is_designated_email(u.email),
            }
            for u in users
        ],
        "hiddenExperts": sum(1 for e in experts if e.is_test),
        "hiddenUsers": sum(1 for u in users if u.is_test),
    }


@router.post("/test-accounts", dependencies=[Depends(require_admin)])
def set_flag(body: FlagIn, db: Session = Depends(get_db)):
    changed = {"experts": 0, "users": 0}
    users = []
    if body.user_ids:
        users += db.query(models.User).filter(models.User.id.in_(body.user_ids)).all()
    if body.emails:
        users += db.query(models.User).filter(models.User.email.in_([e.lower() for e in body.emails])).all()
    experts = db.query(models.ExpertProfile).filter(models.ExpertProfile.id.in_(body.expert_ids)).all() if body.expert_ids else []
    for u in users:
        u.is_test = body.hidden; changed["users"] += 1
        if u.expert_profile is not None and u.expert_profile not in experts:
            experts.append(u.expert_profile)
    for e in experts:
        e.is_test = body.hidden; changed["experts"] += 1
        if e.user is not None:
            e.user.is_test = body.hidden
    db.commit()
    return changed
