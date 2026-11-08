import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex[:10]
    return f"{prefix}{raw}" if prefix else raw


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _id("u_"))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(40), default="")
    role: Mapped[str] = mapped_column(String(20), default="customer")  # customer | expert
    city: Mapped[str] = mapped_column(String(80), default="الرياض")
    # Hidden test/QA/demo account (reversible; see server/test_accounts.py). NULL = not yet classified.
    is_test: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False, index=True)
    # Apple reviewer lane. Authoritative source is APPLE_REVIEWER_EMAILS, not this column and not the email domain.
    is_apple_reviewer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # Social sign-in subjects (Sign in with Apple / Google). Accounts are linked by verified email.
    apple_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    expert_profile = relationship("ExpertProfile", back_populates="user", uselist=False)
    addresses = relationship("Address", back_populates="user", cascade="all, delete-orphan")
    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")


class Address(Base):
    __tablename__ = "addresses"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _id("a_"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(80))
    details: Mapped[str] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column(Float, default=24.7136)
    lng: Mapped[float] = mapped_column(Float, default=46.6753)
    user = relationship("User", back_populates="addresses")


class ExpertProfile(Base):
    __tablename__ = "expert_profiles"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _id("e_"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(120), default="خبيرة تجميل")
    bio: Mapped[str] = mapped_column(Text, default="")
    categories: Mapped[list] = mapped_column(JSON, default=list)
    districts: Mapped[list] = mapped_column(JSON, default=list)
    city: Mapped[str] = mapped_column(String(80), default="الرياض")
    lat: Mapped[float] = mapped_column(Float, default=24.80)
    lng: Mapped[float] = mapped_column(Float, default=46.65)
    modes: Mapped[list] = mapped_column(JSON, default=lambda: ["home"])
    travel_fee: Mapped[int] = mapped_column(Integer, default=25)
    years_exp: Mapped[int] = mapped_column(Integer, default=1)
    nafath_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # mock
    sponsored: Mapped[bool] = mapped_column(Boolean, default=False)
    portfolio: Mapped[list] = mapped_column(JSON, default=list)
    hours: Mapped[dict] = mapped_column(JSON, default=dict)
    cover: Mapped[str] = mapped_column(Text, default="")
    tint: Mapped[str] = mapped_column(String(40), default="lavender")
    iban: Mapped[str] = mapped_column(String(40), default="")
    bank_name: Mapped[str] = mapped_column(String(80), default="")
    freelance_number: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(20), default="approved")  # draft|pending|approved
    rating: Mapped[float] = mapped_column(Float, default=5.0)
    reviews_count: Mapped[int] = mapped_column(Integer, default=0)
    bookings_count: Mapped[int] = mapped_column(Integer, default=0)
    is_test: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="expert_profile")
    services = relationship("Service", back_populates="expert", cascade="all, delete-orphan")


class Service(Base):
    __tablename__ = "services"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _id("s_"))
    expert_id: Mapped[str] = mapped_column(ForeignKey("expert_profiles.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    duration_min: Mapped[int] = mapped_column(Integer, default=60)
    price: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    expert = relationship("ExpertProfile", back_populates="services")


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # DL-xxxxx
    customer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expert_id: Mapped[str] = mapped_column(ForeignKey("expert_profiles.id"), index=True)
    service_ids: Mapped[list] = mapped_column(JSON, default=list)
    mode: Mapped[str] = mapped_column(String(20), default="home")
    date: Mapped[str] = mapped_column(String(10))
    time: Mapped[str] = mapped_column(String(5))
    address_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    subtotal: Mapped[int] = mapped_column(Integer)
    travel_fee: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer)  # services + travel (expert base; no BNPL surcharge)
    deposit: Mapped[float] = mapped_column(Float)  # amount charged now (incl. BNPL surcharge when applicable)
    remaining: Mapped[float] = mapped_column(Float)
    bnpl_surcharge: Mapped[float] = mapped_column(Float, default=0)  # platform-only; offsets Tabby/Tamara fee
    payment_method: Mapped[str] = mapped_column(String(30), default="mada")
    status: Mapped[str] = mapped_column(String(30), default="pending_accept", index=True)
    platform_commission: Mapped[int] = mapped_column(Integer, default=0)
    start_code: Mapped[str] = mapped_column(String(4))
    customer_name: Mapped[str] = mapped_column(String(120))
    expert_name: Mapped[str] = mapped_column(String(120), default="")
    service_name: Mapped[str] = mapped_column(String(200), default="")
    reject_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suggested_time: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    escrow_released: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_provider: Mapped[str] = mapped_column(String(30), default="mock")
    payment_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Set at creation when both parties are server-designated reviewers. Forces mock settlement.
    reviewer_lane: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentLedger(Base):
    __tablename__ = "payment_ledger"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _id("p_"))
    booking_id: Mapped[str] = mapped_column(String(32), index=True)
    expert_id: Mapped[str] = mapped_column(String(32), index=True)
    customer_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # escrow_hold|escrow_release|commission|refund|payout
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="SAR")
    provider: Mapped[str] = mapped_column(String(30), default="mock")
    provider_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _id("r_"))
    expert_id: Mapped[str] = mapped_column(String(32), index=True)
    booking_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    author: Mapped[str] = mapped_column(String(120))
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "expert_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _id("f_"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expert_id: Mapped[str] = mapped_column(String(32), index=True)
    user = relationship("User", back_populates="favorites")


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _id("n_"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(40), default="booking")
    booking_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user = relationship("User", back_populates="notifications")


class Promo(Base):
    __tablename__ = "promos"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _id("pr_"))
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[str] = mapped_column(String(200), default="")
    cta: Mapped[str] = mapped_column(String(80), default="احجزي الآن")
    code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    badge: Mapped[str | None] = mapped_column(String(20), nullable=True)
    theme: Mapped[str] = mapped_column(String(20), default="lavender")
    sponsored: Mapped[bool] = mapped_column(Boolean, default=False)
    expert_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MediaBlob(Base):
    """Uploaded photos/documents (expert portfolio, profile photo, health certificate).
    Stored in Postgres (bytea) because Render's free-tier disk is ephemeral; images are
    resized/compressed client-side (<= ~1600px JPEG) so rows stay small."""
    __tablename__ = "media_blobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _id("m_"))
    owner_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    content_type: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
