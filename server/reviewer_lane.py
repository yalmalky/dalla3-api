"""Server-controlled Apple reviewer lane.

Designation is APPLE_REVIEWER_USER_IDS: exact ids of users that already exist.
It is empty by default. Registration creates a new server-generated id, and
there is no email verification, so a mailbox string is not ownership proof.
A domain, wildcard, email, or client field never grants the lane.
Reviewer customers and reviewer experts can discover and book only each other.
Production experts still have to satisfy phone, IBAN, bank name, and
freelance-document requirements on the server. Nafath is never taken from
the client, so nobody — reviewer or production — gets a verified badge from a request field.
"""
import re

from sqlalchemy.orm import Session

from .config import get_settings
from . import models

# Server ids are u_ + 10 hex chars (see models._id). Anything else is ignored.
_USER_ID = re.compile(r"^u_[0-9a-f]{10}$")
# IBAN shape after spaces are removed (15–34 chars). Not a checksum; it rejects blank and fake short values.
_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")

ACTIVE_BOOKING_STATUSES = models.ACTIVE_BOOKING_STATUSES


def designated_user_ids() -> frozenset[str]:
    raw = get_settings().apple_reviewer_user_ids or ""
    found: list[str] = []
    for part in raw.split(","):
        user_id = part.strip().lower()
        if _USER_ID.fullmatch(user_id):
            found.append(user_id)
    return frozenset(found)


def is_designated_user_id(user_id: str | None) -> bool:
    if not user_id:
        return False
    return user_id.strip().lower() in designated_user_ids()


def is_reviewer_user(user: models.User | None) -> bool:
    return bool(user is not None and is_designated_user_id(user.id))


def is_reviewer_expert(expert: models.ExpertProfile | None) -> bool:
    if expert is None or expert.user is None:
        return False
    return is_designated_user_id(expert.user.id)


def can_discover_expert(viewer: models.User | None, expert: models.ExpertProfile | None) -> bool:
    """Reviewer viewers see only reviewer experts. Everyone else sees only public experts.

    `is_test` hides an expert. It does not let the viewer in. Untrusted test-domain
    accounts therefore cannot read hidden QA experts or the reviewer lane.
    """
    if expert is None or expert.status != "approved":
        return False
    reviewer_expert = is_reviewer_expert(expert)
    if is_reviewer_user(viewer):
        return reviewer_expert
    if reviewer_expert or expert.is_test:
        return False
    return True


def pair_in_reviewer_lane(customer: models.User | None, expert: models.ExpertProfile | None) -> bool:
    return is_reviewer_user(customer) and is_reviewer_expert(expert)


def sync_reviewer_designation(db: Session, user: models.User) -> bool:
    """Persist the allowlist result on this user only. Never scans or updates other rows."""
    designated = is_designated_user_id(user.id)
    dirty = bool(user.is_apple_reviewer) != designated
    if dirty:
        user.is_apple_reviewer = designated
    profile = user.expert_profile
    if designated and profile is not None:
        # Lane experts stay out of the public catalog and cannot keep a client-asserted badge.
        if not profile.is_test:
            profile.is_test = True
            dirty = True
        if profile.nafath_verified:
            profile.nafath_verified = False
            dirty = True
    if dirty:
        db.commit()
        db.refresh(user)
    return designated


def _normalized_iban(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "")).upper()


def production_requirements_met(user: models.User, iban: str, bank_name: str, freelance_number: str) -> bool:
    phone_digits = re.sub(r"\D", "", user.phone or "")
    if len(phone_digits) < 9:
        return False
    if not _IBAN.fullmatch(_normalized_iban(iban)):
        return False
    if not (bank_name or "").strip():
        return False
    if not (freelance_number or "").strip():
        return False
    return True


def apply_expert_onboarding(user: models.User, expert: models.ExpertProfile, body) -> None:
    """Server-side profile rules. Reviewer saves drop identity and payout identifiers."""
    if is_reviewer_user(user):
        expert.iban = ""
        expert.bank_name = ""
        expert.freelance_number = ""
        expert.nafath_verified = False
        expert.is_test = True
        expert.status = "approved"
        return
    expert.iban = _normalized_iban(body.iban)
    expert.bank_name = (body.bank_name or "").strip()
    expert.freelance_number = (body.freelance_number or "").strip()
    # Client `nafath_verified` is not a verification. There is no server-side Nafath check.
    expert.nafath_verified = False
    if user.is_test:
        expert.is_test = True
    expert.status = "approved" if production_requirements_met(
        user, expert.iban, expert.bank_name, expert.freelance_number
    ) else "pending"
