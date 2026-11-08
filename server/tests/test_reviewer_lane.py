"""Apple reviewer lane. Uses the sqlite engine from conftest and never a remote database."""
import os
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, inspect

from server import models
from server.auth import hash_password
from server.config import get_settings
from server.db import Base, SessionLocal, engine
from server.reviewer_lane import designated_emails, production_requirements_met
from server.schema_updates import downgrade_reviewer_schema, upgrade_reviewer_schema

CUSTOMER = "apple-review-customer@dalla3.test"
EXPERT = "apple-review-expert@dalla3.test"
PASSWORD = "secret12"
WHEN = "2027-06-15"
REAL_IBAN = "SA03 8000 0000 6080 1016 7519"
REAL_IBAN_NORMAL = "SA0380000000608010167519"


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@contextmanager
def env(**kwargs):
    old = {key: os.environ.get(key) for key in kwargs}
    for key, value in kwargs.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


def login_or_register(client, email, *, role="customer", phone="", name="مستخدمة"):
    body = {
        "email": email,
        "password": PASSWORD,
        "name": name,
        "phone": phone,
        "role": role,
        "city": "الرياض",
        "reviewerLane": True,  # ignored; designation is not a client field
    }
    res = client.post("/api/auth/register", json=body)
    if res.status_code == 400:
        res = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()


def expert_payload(**overrides):
    body = {
        "display_name": "خبيرة",
        "title": "خبيرة مكياج",
        "categories": ["makeup"],
        "city": "الرياض",
        "modes": ["home"],
        "travel_fee": 25,
        "nafath_verified": True,
        "services": [
            {"category": "makeup", "name": "مكياج سهرة", "duration_min": 90, "price": 200, "description": ""}
        ],
    }
    body.update(overrides)
    return body


def save_expert(client, token, **overrides):
    res = client.put("/api/me/expert", headers=auth(token), json=expert_payload(**overrides))
    assert res.status_code == 200, res.text
    return res.json()


def book(client, token, expert_id, service_id, time="17:00", method="mada"):
    return client.post(
        "/api/bookings",
        headers=auth(token),
        json={
            "expert_id": expert_id,
            "service_ids": [service_id],
            "mode": "home",
            "date": WHEN,
            "time": time,
            "payment_method": method,
        },
    )


def ids_of(rows):
    return {row["id"] for row in rows}


def ensure_hidden_expert():
    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(email="hidden-qa-owner@dalla3.test").one_or_none()
        if user and user.expert_profile:
            service = user.expert_profile.services[0]
            return user.expert_profile.id, service.id
        user = models.User(
            email="hidden-qa-owner@dalla3.test",
            password_hash=hash_password(PASSWORD),
            name="مالكة مخفية",
            role="expert",
            is_test=True,
            is_apple_reviewer=False,
        )
        db.add(user)
        db.flush()
        expert = models.ExpertProfile(
            user_id=user.id,
            display_name="خبيرة مخفية",
            status="approved",
            is_test=True,
            nafath_verified=True,
            categories=["makeup"],
        )
        db.add(expert)
        db.flush()
        service = models.Service(
            expert_id=expert.id, category="makeup", name="خدمة مخفية", price=90, duration_min=60
        )
        db.add(service)
        db.commit()
        return expert.id, service.id
    finally:
        db.close()


def test_suite_stays_on_sqlite():
    assert engine.dialect.name == "sqlite"


def test_schema_upgrade_is_idempotent_and_rollback_drops_columns():
    path = "/tmp/dalla3-reviewer-schema-rollback.db"
    if os.path.exists(path):
        os.remove(path)
    local = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(local)
    assert upgrade_reviewer_schema(local) == []
    assert "is_apple_reviewer" in {c["name"] for c in inspect(local).get_columns("users")}
    assert "reviewer_lane" in {c["name"] for c in inspect(local).get_columns("bookings")}

    removed = downgrade_reviewer_schema(local)
    assert "users.is_apple_reviewer" in removed
    assert "bookings.reviewer_lane" in removed
    assert "is_apple_reviewer" not in {c["name"] for c in inspect(local).get_columns("users")}

    added = upgrade_reviewer_schema(local)
    assert "users.is_apple_reviewer" in added
    assert "bookings.reviewer_lane" in added
    assert upgrade_reviewer_schema(local) == []
    local.dispose()


def test_domain_and_wildcard_entries_are_not_designation():
    with env(APPLE_REVIEWER_EMAILS="dalla3.test,@dalla3.test,*@dalla3.test"):
        assert designated_emails() == frozenset()


def test_normal_onboarding_unaffected_and_requirements_enforced(client):
    """A completed non-reviewer application still publishes. The reviewer waiver does not apply,
    and the client cannot grant itself a Nafath badge or skip the production requirements."""
    ready = login_or_register(
        client, "nora.expert@gmail.com", role="expert", phone="0551234567", name="نورة"
    )
    assert ready["user"]["reviewerLane"] is False
    published = save_expert(
        client,
        ready["access_token"],
        display_name="نورة الخبيرة",
        iban=REAL_IBAN,
        bank_name="Al Rajhi",
        freelance_number="FL-123456",
        nafath_verified=True,
    )
    assert published["reviewerLane"] is False
    assert published["nafathVerified"] is False
    assert published["status"] == "approved"
    assert published["services"][0]["name"] == "مكياج سهرة"

    listed = client.get("/api/experts")
    assert listed.status_code == 200
    assert published["id"] in ids_of(listed.json())
    public = next(row for row in listed.json() if row["id"] == published["id"])
    assert public["nafathVerified"] is False
    assert public["reviewerLane"] is False

    db = SessionLocal()
    try:
        row = db.get(models.ExpertProfile, published["id"])
        assert row.iban == REAL_IBAN_NORMAL
        assert row.bank_name == "Al Rajhi"
        assert row.freelance_number == "FL-123456"
        assert row.nafath_verified is False
        assert row.is_test is False
        assert row.user.is_apple_reviewer is False
    finally:
        db.close()

    incomplete = login_or_register(
        client, "incomplete.expert@gmail.com", role="expert", phone="", name="ناقصة"
    )
    held = save_expert(
        client,
        incomplete["access_token"],
        display_name="بدون وثائق",
        nafath_verified=True,
        iban="",
        bank_name="",
        freelance_number="",
    )
    assert held["reviewerLane"] is False
    assert held["nafathVerified"] is False
    assert held["status"] == "pending"
    assert held["id"] not in ids_of(client.get("/api/experts").json())
    assert client.get(f"/api/experts/{held['id']}").status_code == 404

    me = client.get("/api/auth/me", headers=auth(ready["access_token"]))
    assert me.json()["reviewerLane"] is False


def test_untrusted_test_email_cannot_access_hidden_or_reviewer_experts(client):
    hidden_id, hidden_service = ensure_hidden_expert()
    reviewer = login_or_register(client, EXPERT, role="expert", phone="", name="مراجعة خبيرة")
    reviewer_profile = save_expert(client, reviewer["access_token"], display_name="خبيرة المراجعة")
    real = login_or_register(
        client, "public.expert@gmail.com", role="expert", phone="0550001112", name="عامة"
    )
    real_profile = save_expert(
        client,
        real["access_token"],
        display_name="خبيرة عامة",
        iban=REAL_IBAN,
        bank_name="SNB",
        freelance_number="FL-999111",
    )

    outsider = login_or_register(client, "untrusted-qa@dalla3.test", role="customer", name="تجربة")
    assert outsider["user"]["reviewerLane"] is False
    token = outsider["access_token"]
    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(email="untrusted-qa@dalla3.test").one()
        assert user.is_test is True
        assert user.is_apple_reviewer is False
    finally:
        db.close()

    listed = ids_of(client.get("/api/experts", headers=auth(token)).json())
    anon = ids_of(client.get("/api/experts").json())
    assert real_profile["id"] in listed and real_profile["id"] in anon
    assert hidden_id not in listed and hidden_id not in anon
    assert reviewer_profile["id"] not in listed and reviewer_profile["id"] not in anon

    for expert_id in (hidden_id, reviewer_profile["id"]):
        for path in (
            f"/api/experts/{expert_id}",
            f"/api/experts/{expert_id}/services",
            f"/api/experts/{expert_id}/reviews",
            f"/api/experts/{expert_id}/slots?date={WHEN}",
        ):
            assert client.get(path, headers=auth(token)).status_code == 404
            assert client.get(path).status_code == 404
        assert book(client, token, expert_id, hidden_service).status_code == 404

    favorite = client.post(f"/api/me/favorites/{hidden_id}", headers=auth(token))
    assert favorite.status_code == 404
    assert hidden_id not in client.get("/api/me/favorites", headers=auth(token)).json()


def test_public_signup_cannot_self_grant_by_domain_and_revocation_is_immediate(client):
    with env(APPLE_REVIEWER_EMAILS=""):
        created = login_or_register(client, "new-qa@dalla3.test")
        assert created["user"]["reviewerLane"] is False
        existing = client.post("/api/auth/login", json={"email": CUSTOMER, "password": PASSWORD})
        if existing.status_code == 200:
            assert existing.json()["user"]["reviewerLane"] is False
            listed = ids_of(client.get("/api/experts", headers=auth(existing.json()["access_token"])).json())
            reviewer = SessionLocal()
            try:
                profile = (
                    reviewer.query(models.ExpertProfile)
                    .join(models.User)
                    .filter(models.User.email == EXPERT)
                    .one_or_none()
                )
                if profile is not None:
                    assert profile.id not in listed
            finally:
                reviewer.close()

    # Restored allowlist designates the exact mailbox only.
    designated = login_or_register(client, CUSTOMER, name="عميلة المراجعة")
    assert designated["user"]["reviewerLane"] is True
    profile = client.get("/api/me/profile", headers=auth(designated["access_token"]))
    assert profile.json()["reviewerLane"] is True
    lookalike = login_or_register(client, "apple-review-customer@dalla3.test.evil.com")
    # evil.com is not a test domain and is not on the allowlist.
    assert lookalike["user"]["reviewerLane"] is False


def test_designated_reviewer_customer_cannot_book_real_or_hidden_experts(client):
    hidden_id, hidden_service = ensure_hidden_expert()
    real = login_or_register(
        client, "bookable.real@gmail.com", role="expert", phone="0551239876", name="حقيقية"
    )
    real_profile = save_expert(
        client,
        real["access_token"],
        display_name="خبيرة حقيقية",
        iban=REAL_IBAN,
        bank_name="Al Rajhi",
        freelance_number="FL-555000",
    )
    customer = login_or_register(client, CUSTOMER, name="عميلة المراجعة")
    assert customer["user"]["reviewerLane"] is True
    token = customer["access_token"]
    listed = ids_of(client.get("/api/experts", headers=auth(token)).json())
    assert real_profile["id"] not in listed
    assert hidden_id not in listed

    real_service = real_profile["services"][0]["id"]
    assert book(client, token, real_profile["id"], real_service).status_code == 404
    assert book(client, token, hidden_id, hidden_service).status_code == 404
    quote = client.post(
        "/api/bookings/quote",
        headers=auth(token),
        json={
            "expert_id": real_profile["id"],
            "service_ids": [real_service],
            "mode": "home",
            "date": WHEN,
            "time": "17:00",
            "payment_method": "mada",
        },
    )
    assert quote.status_code == 404
    favorite = client.post(f"/api/me/favorites/{real_profile['id']}", headers=auth(token))
    assert favorite.status_code == 404


def test_permitted_pair_can_book_accept_and_cancel(client):
    customer = login_or_register(client, CUSTOMER, name="عميلة المراجعة")
    expert = login_or_register(client, EXPERT, role="expert", phone="", name="مراجعة خبيرة")
    profile = save_expert(
        client,
        expert["access_token"],
        display_name="خبيرة المراجعة",
        iban="SA0380000000608010167519",
        bank_name="Fake Bank",
        freelance_number="000000",
        nafath_verified=True,
    )
    assert profile["reviewerLane"] is True
    assert profile["nafathVerified"] is False
    assert profile["status"] == "approved"
    assert profile["id"] not in ids_of(client.get("/api/experts").json())
    assert profile["id"] in ids_of(
        client.get("/api/experts", headers=auth(customer["access_token"])).json()
    )

    db = SessionLocal()
    try:
        row = db.get(models.ExpertProfile, profile["id"])
        assert row.iban == ""
        assert row.bank_name == ""
        assert row.freelance_number == ""
        assert row.nafath_verified is False
        assert row.is_test is True
        assert row.user.phone == ""
        assert row.user.is_apple_reviewer is True
    finally:
        db.close()

    service_id = profile["services"][0]["id"]
    created = book(client, customer["access_token"], profile["id"], service_id, time="15:30")
    assert created.status_code == 200, created.text
    booking = created.json()
    assert booking["status"] == "pending_accept"
    assert booking["reviewerLane"] is True
    assert booking["paymentProvider"] == "mock"
    assert booking["paymentRef"].startswith("mock_")

    accepted = client.post(f"/api/bookings/{booking['id']}/accept", headers=auth(expert["access_token"]))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "confirmed"

    cancelled = client.post(f"/api/bookings/{booking['id']}/cancel", headers=auth(customer["access_token"]))
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["paymentProvider"] == "mock"

    db = SessionLocal()
    try:
        row = db.get(models.Booking, booking["id"])
        assert row.reviewer_lane is True
        assert row.payment_provider == "mock"
        kinds = {
            (line.kind, line.provider)
            for line in db.query(models.PaymentLedger).filter_by(booking_id=booking["id"]).all()
        }
        assert ("escrow_hold", "mock") in kinds
        assert ("refund", "mock") in kinds
    finally:
        db.close()

    stranger = login_or_register(client, "stranger.customer@gmail.com", phone="0551112233")
    assert client.get(f"/api/bookings/{booking['id']}", headers=auth(stranger["access_token"])).status_code == 403


def test_duplicate_active_slot_is_rejected_until_the_first_booking_ends(client):
    customer = login_or_register(client, CUSTOMER, name="عميلة المراجعة")
    expert = login_or_register(client, EXPERT, role="expert", phone="", name="مراجعة خبيرة")
    profile = save_expert(client, expert["access_token"], display_name="خبيرة المراجعة")
    service_id = profile["services"][0]["id"]

    first = book(client, customer["access_token"], profile["id"], service_id, time="18:30")
    assert first.status_code == 200, first.text
    second = book(client, customer["access_token"], profile["id"], service_id, time="18:30")
    assert second.status_code == 409

    cancelled = client.post(
        f"/api/bookings/{first.json()['id']}/cancel", headers=auth(customer["access_token"])
    )
    assert cancelled.status_code == 200, cancelled.text
    again = book(client, customer["access_token"], profile["id"], service_id, time="18:30")
    assert again.status_code == 200, again.text
    client.post(f"/api/bookings/{again.json()['id']}/cancel", headers=auth(customer["access_token"]))


def test_reviewer_payment_is_forced_to_mock(client):
    customer = login_or_register(client, CUSTOMER, name="عميلة المراجعة")
    expert = login_or_register(client, EXPERT, role="expert", phone="", name="مراجعة خبيرة")
    profile = save_expert(client, expert["access_token"], display_name="خبيرة المراجعة")
    real = login_or_register(
        client, "pay.real@gmail.com", role="expert", phone="0557776655", name="دفع"
    )
    real_profile = save_expert(
        client,
        real["access_token"],
        display_name="خبيرة الدفع",
        iban=REAL_IBAN,
        bank_name="Al Rajhi",
        freelance_number="FL-777666",
    )
    real_customer = login_or_register(client, "pay.customer@gmail.com", phone="0557776644", name="عميلة دفع")

    with env(PAYMENT_PROVIDER="moyasar"):
        lane = book(
            client,
            customer["access_token"],
            profile["id"],
            profile["services"][0]["id"],
            time="20:00",
            method="mada",
        )
        assert lane.status_code == 200, lane.text
        assert lane.json()["paymentProvider"] == "mock"
        assert lane.json()["reviewerLane"] is True
        assert lane.json()["paymentRef"].startswith("mock_")

        with pytest.raises(RuntimeError, match="Moyasar"):
            book(
                client,
                real_customer["access_token"],
                real_profile["id"],
                real_profile["services"][0]["id"],
                time="21:30",
            )

    db = SessionLocal()
    try:
        row = db.get(models.Booking, lane.json()["id"])
        assert row.payment_provider == "mock"
        assert row.reviewer_lane is True
        assert (
            db.query(models.Booking)
            .filter_by(customer_id=real_customer["user"]["id"], expert_id=real_profile["id"])
            .count()
            == 0
        )
    finally:
        db.close()
    client.post(f"/api/bookings/{lane.json()['id']}/cancel", headers=auth(customer["access_token"]))


def test_production_requirement_helper_rejects_blank_identifiers():
    user = models.User(email="helper@gmail.com", password_hash="x", name="ن", phone="0551234567")
    assert production_requirements_met(user, REAL_IBAN, "Al Rajhi", "FL-1") is True
    assert production_requirements_met(user, "", "Al Rajhi", "FL-1") is False
    assert production_requirements_met(user, "0000", "Al Rajhi", "FL-1") is False
    user.phone = ""
    assert production_requirements_met(user, REAL_IBAN, "Al Rajhi", "FL-1") is False


def test_admin_list_stays_closed_without_a_token(client):
    assert client.get("/api/admin/test-accounts").status_code == 404
