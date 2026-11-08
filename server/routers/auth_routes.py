from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..auth import create_token, get_current_user, hash_password, verify_password
from ..db import get_db
from ..test_accounts import is_test_email
from ..reviewer_lane import is_designated_user_id, sync_reviewer_designation
import secrets

from ..config import get_settings
from ..schemas import LoginIn, RegisterIn, SocialIn, TokenOut
from ..social import verify_apple, verify_google

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
        # True only when this existing user id is in APPLE_REVIEWER_USER_IDS.
        "reviewerLane": is_designated_user_id(u.id),
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
        is_test=is_test_email(body.email),  # QA sign-ups (e.g. @dalla3.test) stay hidden
        is_apple_reviewer=False,  # a new id is not designated; email and client input cannot self-grant
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    sync_reviewer_designation(db, user)
    return TokenOut(access_token=create_token(user.id, user.role), user=_user_dict(user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == body.email.lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "الإيميل أو كلمة المرور غلط")
    sync_reviewer_designation(db, user)
    return TokenOut(access_token=create_token(user.id, user.role), user=_user_dict(user))


def _social_login(db: Session, provider: str, claims: dict, name: str) -> TokenOut:
    sub = claims.get("sub")
    email = (claims.get("email") or "").lower()
    verified = str(claims.get("email_verified", "true")).lower() == "true"
    col = models.User.apple_sub if provider == "apple" else models.User.google_sub
    user = db.query(models.User).filter(col == sub).first()
    if not user and email and verified:
        user = db.query(models.User).filter(models.User.email == email).first()  # link existing email account
    is_new = False
    if not user:
        if not email:
            raise HTTPException(400, "ما وصلنا إيميل من الحساب — جرّبي الدخول بالإيميل")
        user = models.User(
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(24)),  # unusable random password
            name=(name or claims.get("name") or email.split("@")[0])[:120],
            role="customer",  # role is chosen later (customer by default; «انضمي كخبيرة» upgrades)
            is_test=is_test_email(email),
            is_apple_reviewer=False,
        )
        db.add(user)
        is_new = True
    if provider == "apple":
        user.apple_sub = sub
    else:
        user.google_sub = sub
    if name and (not user.name or user.name == email.split("@")[0]):
        user.name = name[:120]
    db.commit()
    db.refresh(user)
    sync_reviewer_designation(db, user)
    out = _user_dict(user)
    out["isNew"] = is_new
    return TokenOut(access_token=create_token(user.id, user.role), user=out)


@router.post("/apple", response_model=TokenOut)
def apple(body: SocialIn, db: Session = Depends(get_db)):
    auds = [a.strip() for a in get_settings().apple_client_ids.split(",") if a.strip()]
    try:
        claims = verify_apple(body.id_token, auds)
    except Exception:
        raise HTTPException(401, "ما قدرنا نتحقق من حساب Apple")
    return _social_login(db, "apple", claims, body.name.strip())


@router.post("/google", response_model=TokenOut)
def google(body: SocialIn, db: Session = Depends(get_db)):
    auds = [a.strip() for a in get_settings().google_client_ids.split(",") if a.strip()]
    if not auds:
        raise HTTPException(503, "الدخول عبر Google غير مفعّل حالياً")
    try:
        claims = verify_google(body.id_token, auds)
    except Exception:
        raise HTTPException(401, "ما قدرنا نتحقق من حساب Google")
    return _social_login(db, "google", claims, body.name.strip())


@router.get("/providers")
def providers():
    s = get_settings()
    return {"apple": bool(s.apple_client_ids.strip()), "google": bool(s.google_client_ids.strip())}


@router.get("/me")
def me(user: models.User = Depends(get_current_user)):
    return _user_dict(user)
