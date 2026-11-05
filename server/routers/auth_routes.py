from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..auth import create_token, get_current_user, hash_password, verify_password
from ..db import get_db
from ..schemas import LoginIn, RegisterIn, TokenOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_dict(u: models.User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "phone": u.phone,
        "role": u.role,
        "city": u.city,
        "expertId": u.expert_profile.id if u.expert_profile else None,
    }


@router.post("/register", response_model=TokenOut)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if body.role not in ("customer", "expert"):
        raise HTTPException(400, "الدور لازم يكون عميلة أو خبيرة")
    if db.query(models.User).filter(models.User.email == body.email.lower()).first():
        raise HTTPException(400, "الإيميل مسجّل من قبل")
    user = models.User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        name=body.name,
        phone=body.phone,
        role=body.role,
        city=body.city,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_token(user.id, user.role), user=_user_dict(user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == body.email.lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "الإيميل أو كلمة المرور غلط")
    return TokenOut(access_token=create_token(user.id, user.role), user=_user_dict(user))


@router.get("/me")
def me(user: models.User = Depends(get_current_user)):
    return _user_dict(user)
