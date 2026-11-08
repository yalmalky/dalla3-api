"""Apple reviewer lane. Uses the sqlite engine from conftest and never a remote database."""
import os
import threading
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from server import models
from server.auth import hash_password
from server.config import get_settings
from server.db import Base, SessionLocal, engine
from server.reviewer_lane import designated_user_ids, production_requirements_met
from server.schema_updates import downgrade_reviewer_schema, upgrade_reviewer_schema

CUSTOMER = "apple-review-customer@dalla3.test"
EXPERT = "apple-review-expert@dalla3.test"
PASSWORD = "secret12"
WHEN = "2027-06-15"
REAL_IBAN = "SA03 8000 0000 6080 1016 7519"
REAL_IBAN_NORMAL = "SA0380000000608010167519"
INTENDED_EMAILS = f"{CUSTOMER},{EXPERT}"


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


@contextmanager
def bind_users(*user_ids: str):
    with env(APPLE_REVIEWER_USER_IDS=",".join(user_ids), APPLE_REVIEWER_EMAILS=INTENDED_EMAILS):
        yield


def login_or_register(client, email, *, role="customer", phone="", name="مستخدمة"):
    body = {
        "email": email,
        "password": PASSWORD,
        "name": name,
        "phone": phone,
        "role": role,
        "city": "الرياض",
        "reviewerLane": True,
        "is_apple_reviewer": True,
        "nafathVerified": True,
    }
    res = client.post("/api/auth/register", json=body)
    if res.status_code == 400:
        res = client.post("/api/auth/login", json={"email": email, "password": PASSWORD, "reviewerLane": True})
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
        "reviewerLane": True,
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


def user_by_email(email: str) -> models.User:
    db = SessionLocal()
    try:
        return db.query(models.User).filter_by(email=email).one()
    finally:
        db.close()


def ensure_hidden_expert():
    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(email="hidden-qa-owner@dalla3.test").one_or_none()
        if user and user.expert_profile:
            return user.expert_profile.id, user.expert_profile.services[0].id
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


def assert_private(client, token, expert_id, service_id, *, hidden_from_anonymous: bool):
    """Discovery, services, reviews, slots, quote, booking, and favorites stay closed for this caller."""
    headers = auth(token)
    assert expert_id not in ids_of(client.get("/api/experts", headers=headers).json())
    for path in (
        f"/api/experts/{expert_id}",
        f"/api/experts/{expert_id}/services",
        f"/api/experts/{expert_id}/reviews",
        f"/api/experts/{expert_id}/slots?date={WHEN}",
    ):
        assert client.get(path, headers=headers).status_code == 404
        if hidden_from_anonymous:
            assert client.get(path).status_code == 404
    assert book(client, token, expert_id, service_id).status_code == 404
    quote = client.post(
        "/api/bookings/quote",
        headers=headers,
        json={
            "expert_id": expert_id,
            "service_ids": [service_id],
            "mode": "home",
            "date": WHEN,
            "time": "17:00",
            "payment_method": "mada",
        },
    )
    assert quote.status_code == 404
    favorite = client.post(f"/api/me/favorites/{expert_id}", headers=headers)
    assert favorite.status_code == 404
    assert expert_id not in client.get("/api/me/favorites", headers=headers).json()


def test_suite_stays_on_sqlite():
    assert engine.dialect.name == "sqlite"


def test_schema_upgrade_is_idempotent_and_rollback_drops_columns_and_slot_index():
    path = "/tmp/dalla3-reviewer-schema-rollback.db"
    if os.path.exists(path):
        os.remove(path)
    local = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(local)
    assert upgrade_reviewer_schema(local) == []
    names = {idx["name"] for idx in inspect(local).get_indexes("bookings")}
    assert "uq_booking_active_slot" in names
    assert "is_apple_reviewer" in {c["name"] for c in inspect(local).get_columns("users")}

    removed = downgrade_reviewer_schema(local)
    assert "bookings.uq_booking_active_slot" in removed
    assert "users.is_apple_reviewer" in removed
    assert "uq_booking_active_slot" not in {idx["name"] for idx in inspect(local).get_indexes("bookings")}
    assert "is_apple_reviewer" not in {c["name"] for c in inspect(local).get_columns("users")}

    added = upgrade_reviewer_schema(local)
    assert "users.is_apple_reviewer" in added
    assert "bookings.reviewer_lane" in added
    assert "bookings.uq_booking_active_slot" in added
    assert upgrade_reviewer_schema(local) == []
    local.dispose()


def test_malformed_and_wildcard_config_designates_nobody():
    junk = [
        "",
        "*",
        "u_*",
        "u_",
        "u_123",
        "u_0123456789extra",
        "e_0123456789",
        "*@dalla3.test",
        "@dalla3.test",
        "dalla3.test",
        CUSTOMER,
        EXPERT,
        f"{CUSTOMER},{EXPERT}",
        "u_deadbeef00;drop",
        "' OR 1=1",
        "../u_deadbeef00",
    ]
    for raw in junk:
        with env(APPLE_REVIEWER_USER_IDS=raw, APPLE_REVIEWER_EMAILS=INTENDED_EMAILS):
            assert designated_user_ids() == frozenset()
    with env(APPLE_REVIEWER_USER_IDS=f"*,{CUSTOMER},u_*,u_deadbeef00,e_0123456789"):
        assert designated_user_ids() == frozenset({"u_deadbeef00"})


def test_signup_of_intended_mailbox_before_designation_grants_nothing(client):
    """The email allowlist and a client flag must not make the first registrant a reviewer."""
    with env(APPLE_REVIEWER_USER_IDS="", APPLE_REVIEWER_EMAILS=INTENDED_EMAILS):
        stranger = login_or_register(client, EXPERT, role="expert", phone="", name="غريبة")
        customer = login_or_register(client, CUSTOMER, name="عميلة المراجعة")
    assert stranger["user"]["reviewerLane"] is False
    assert customer["user"]["reviewerLane"] is False
    db = SessionLocal()
    try:
        expert_user = db.query(models.User).filter_by(email=EXPERT).one()
        customer_user = db.query(models.User).filter_by(email=CUSTOMER).one()
        assert expert_user.is_apple_reviewer is False
        assert customer_user.is_apple_reviewer is False
        assert expert_user.is_test is True
    finally:
        db.close()
    me = client.get("/api/auth/me", headers=auth(stranger["access_token"]))
    assert me.json()["reviewerLane"] is False
    profile = client.get("/api/me/profile", headers=auth(customer["access_token"]))
    assert profile.json()["reviewerLane"] is False

    # A pre-chosen id that is not this new row still does not attach to the signup.
    with env(APPLE_REVIEWER_USER_IDS="u_deadbeef00", APPLE_REVIEWER_EMAILS=INTENDED_EMAILS):
        again = client.post("/api/auth/login", json={"email": EXPERT, "password": PASSWORD, "reviewerLane": True})
        assert again.status_code == 200
        assert again.json()["user"]["reviewerLane"] is False
        assert again.json()["user"]["id"] != "u_deadbeef00"


def test_nonreviewer_cannot_claim_lane_or_keep_fake_verified_fields(client):
    login_or_register(client, EXPERT, role="expert", phone="", name="مراجعة خبيرة")
    token = client.post("/api/auth/login", json={"email": EXPERT, "password": PASSWORD}).json()["access_token"]
    held = save_expert(
        client,
        token,
        display_name="قبل التعيين",
        iban=REAL_IBAN,
        bank_name="Fake Bank",
        freelance_number="000000",
        nafath_verified=True,
    )
    assert held["reviewerLane"] is False
    assert held["nafathVerified"] is False
    assert held["status"] == "pending"
    assert held["id"] not in ids_of(client.get("/api/experts").json())
    db = SessionLocal()
    try:
        row = db.get(models.ExpertProfile, held["id"])
        assert row.nafath_verified is False
        assert row.user.is_apple_reviewer is False
        assert row.status == "pending"
    finally:
        db.close()


def test_normal_onboarding_unaffected_and_requirements_enforced(client):
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
    assert published["id"] in ids_of(client.get("/api/experts").json())
    public = next(row for row in client.get("/api/experts").json() if row["id"] == published["id"])
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

    incomplete = login_or_register(client, "incomplete.expert@gmail.com", role="expert", phone="", name="ناقصة")
    held = save_expert(
        client,
        incomplete["access_token"],
        display_name="بدون وثائق",
        nafath_verified=True,
        iban="0000",
        bank_name="",
        freelance_number="",
    )
    assert held["reviewerLane"] is False
    assert held["nafathVerified"] is False
    assert held["status"] == "pending"
    assert held["id"] not in ids_of(client.get("/api/experts").json())
    assert client.get(f"/api/experts/{held['id']}").status_code == 404


def test_cross_lane_discovery_services_slots_favorites_and_booking(client):
    hidden_id, hidden_service = ensure_hidden_expert()
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
    customer = login_or_register(client, CUSTOMER, name="عميلة المراجعة")
    expert = login_or_register(client, EXPERT, role="expert", phone="", name="مراجعة خبيرة")
    # Not designated yet: the intended expert profile stays off the public catalog and off the lane.
    with bind_users(customer["user"]["id"], expert["user"]["id"]):
        expert_profile = save_expert(client, expert["access_token"], display_name="خبيرة المراجعة")
        outsider = login_or_register(client, "untrusted-qa@dalla3.test", name="تجربة")
        assert outsider["user"]["reviewerLane"] is False
        db = SessionLocal()
        try:
            row = db.query(models.User).filter_by(email="untrusted-qa@dalla3.test").one()
            assert row.is_test is True
            assert row.is_apple_reviewer is False
        finally:
            db.close()

        real_service = real_profile["services"][0]["id"]
        reviewer_service = expert_profile["services"][0]["id"]
        assert_private(client, outsider["access_token"], hidden_id, hidden_service, hidden_from_anonymous=True)
        assert_private(
            client, outsider["access_token"], expert_profile["id"], reviewer_service, hidden_from_anonymous=True
        )
        assert real_profile["id"] in ids_of(
            client.get("/api/experts", headers=auth(outsider["access_token"])).json()
        )
        assert_private(
            client, customer["access_token"], real_profile["id"], real_service, hidden_from_anonymous=False
        )
        assert_private(client, customer["access_token"], hidden_id, hidden_service, hidden_from_anonymous=True)
        assert expert_profile["id"] in ids_of(
            client.get("/api/experts", headers=auth(customer["access_token"])).json()
        )
        assert expert_profile["id"] not in ids_of(client.get("/api/experts").json())


def test_permitted_pair_only_after_both_existing_ids_are_bound(client):
    customer = login_or_register(client, CUSTOMER, name="عميلة المراجعة")
    expert = login_or_register(client, EXPERT, role="expert", phone="", name="مراجعة خبيرة")
    # Binding only one side does not open the pair.
    with bind_users(customer["user"]["id"]):
        refreshed = client.post("/api/auth/login", json={"email": CUSTOMER, "password": PASSWORD})
        assert refreshed.json()["user"]["reviewerLane"] is True
        expert_login = client.post("/api/auth/login", json={"email": EXPERT, "password": PASSWORD})
        assert expert_login.json()["user"]["reviewerLane"] is False

    with bind_users(customer["user"]["id"], expert["user"]["id"]):
        customer = login_or_register(client, CUSTOMER, name="عميلة المراجعة")
        expert = login_or_register(client, EXPERT, role="expert", phone="", name="مراجعة خبيرة")
        assert customer["user"]["reviewerLane"] is True
        assert expert["user"]["reviewerLane"] is True
        profile = save_expert(
            client,
            expert["access_token"],
            display_name="خبيرة المراجعة",
            iban=REAL_IBAN,
            bank_name="Fake Bank",
            freelance_number="000000",
            nafath_verified=True,
        )
        assert profile["reviewerLane"] is True
        assert profile["nafathVerified"] is False
        assert profile["status"] == "approved"
        assert profile["id"] not in ids_of(client.get("/api/experts").json())
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

        created = book(
            client, customer["access_token"], profile["id"], profile["services"][0]["id"], time="15:30"
        )
        assert created.status_code == 200, created.text
        booking = created.json()
        assert booking["status"] == "pending_accept"
        assert booking["reviewerLane"] is True
        assert booking["paymentProvider"] == "mock"
        assert booking["paymentRef"].startswith("mock_")

        accepted = client.post(
            f"/api/bookings/{booking['id']}/accept", headers=auth(expert["access_token"])
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "confirmed"
        cancelled = client.post(
            f"/api/bookings/{booking['id']}/cancel", headers=auth(customer["access_token"])
        )
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

    # Removing the ids revokes the lane on the next request. The old booking stays marked.
    revoked = client.post("/api/auth/login", json={"email": CUSTOMER, "password": PASSWORD})
    assert revoked.json()["user"]["reviewerLane"] is False


def test_duplicate_active_slot_is_rejected_until_the_first_booking_ends(client):
    customer = login_or_register(client, CUSTOMER, name="عميلة المراجعة")
    expert = login_or_register(client, EXPERT, role="expert", phone="", name="مراجعة خبيرة")
    with bind_users(customer["user"]["id"], expert["user"]["id"]):
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


def test_active_slot_index_rejects_a_second_active_row_and_allows_reuse_after_cancel(client):
    db = SessionLocal()
    try:
        owner = models.User(
            email="slot-index-owner@gmail.com",
            password_hash=hash_password(PASSWORD),
            name="فهرس",
            role="expert",
            phone="0551002000",
            is_apple_reviewer=False,
        )
        db.add(owner)
        db.flush()
        expert = models.ExpertProfile(
            user_id=owner.id, display_name="فهرس", status="approved", is_test=False, nafath_verified=False
        )
        db.add(expert)
        db.commit()
        customer_id, expert_id = owner.id, expert.id
    finally:
        db.close()

    def make(suffix: str, status: str) -> models.Booking:
        return models.Booking(
            id=f"DL-slot-{suffix}",
            customer_id=customer_id,
            expert_id=expert_id,
            service_ids=[],
            mode="home",
            date="2027-08-01",
            time="14:00",
            subtotal=100,
            travel_fee=0,
            total=100,
            deposit=100,
            remaining=0,
            status=status,
            start_code="1234",
            customer_name="فهرس",
            expert_name="فهرس",
            payment_provider="mock",
            reviewer_lane=False,
        )

    first = SessionLocal()
    second = SessionLocal()
    try:
        first.add(make("a", "pending_accept"))
        first.commit()
        second.add(make("b", "confirmed"))
        with pytest.raises(IntegrityError):
            second.commit()
        second.rollback()
        active = first.query(models.Booking).filter_by(id="DL-slot-a").one()
        active.status = "cancelled"
        first.commit()
        second.add(make("c", "pending_accept"))
        second.commit()
    finally:
        first.close()
        second.close()

    # Two commits racing on a free active slot: one wins, the unique index rejects the other.
    barrier = threading.Barrier(2)
    results: list[str] = []

    def race(suffix: str):
        session = SessionLocal()
        try:
            barrier.wait(timeout=5)
            row = make(suffix, "pending_accept")
            row.date = "2027-08-02"
            row.time = "16:00"
            session.add(row)
            session.commit()
            results.append("ok")
        except IntegrityError:
            session.rollback()
            results.append("conflict")
        finally:
            session.close()

    threads = [threading.Thread(target=race, args=(suffix,)) for suffix in ("race1", "race2")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    assert sorted(results) == ["conflict", "ok"]


def test_reviewer_payment_is_forced_to_mock(client):
    customer = login_or_register(client, CUSTOMER, name="عميلة المراجعة")
    expert = login_or_register(client, EXPERT, role="expert", phone="", name="مراجعة خبيرة")
    real = login_or_register(client, "pay.real@gmail.com", role="expert", phone="0557776655", name="دفع")
    real_profile = save_expert(
        client,
        real["access_token"],
        display_name="خبيرة الدفع",
        iban=REAL_IBAN,
        bank_name="Al Rajhi",
        freelance_number="FL-777666",
    )
    real_customer = login_or_register(client, "pay.customer@gmail.com", phone="0557776644", name="عميلة دفع")
    with bind_users(customer["user"]["id"], expert["user"]["id"]):
        profile = save_expert(client, expert["access_token"], display_name="خبيرة المراجعة")
        with env(PAYMENT_PROVIDER="moyasar", APPLE_REVIEWER_USER_IDS=f"{customer['user']['id']},{expert['user']['id']}"):
            lane = book(
                client,
                customer["access_token"],
                profile["id"],
                profile["services"][0]["id"],
                time="20:00",
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
