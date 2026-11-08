"""Test / QA / demo accounts: hidden (never deleted) via the reversible `is_test` flag.

- Hidden experts are excluded from public listings, search, expert pages, quotes, bookings, favorites and promos.
- `is_test` does not grant access. A test-domain signup cannot read hidden experts or the Apple reviewer lane.
- Hidden customers keep their data; they are flagged so they can be excluded from stats/exports.
- `classify_existing` runs ONCE per row (only where is_test IS NULL).
- Public sign-up sets is_test from the email heuristic (see auth routes). That flag is not reviewer designation.
  Reviewer access is only APPLE_REVIEWER_USER_IDS: exact ids of accounts that already exist.
- After classification, hide/unhide is via `/api/admin/test-accounts` (header X-Admin-Token = env ADMIN_TOKEN) or SQL:
      UPDATE expert_profiles SET is_test = false WHERE id = 'e_…';
      UPDATE users SET is_test = false WHERE email = '…';
"""
import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import models

TEST_EMAIL_DOMAINS = {"dalla3.test", "example.com", "example.org", "example.net", "test.com", "test.local", "mailinator.com"}
TEST_EMAIL_LOCAL = re.compile(r"^(qa|test|demo|debug)([._+-]|\d|$)|\+(qa|test|demo)\b", re.I)
# QA / demo store names created during development (exact display names).
TEST_EXPERT_NAMES = {"سارة الميكب", "خبيرة كروس", "نورة العائلة"}


def is_test_email(email: str | None) -> bool:
    e = (email or "").strip().lower()
    if "@" not in e:
        return False
    local, domain = e.rsplit("@", 1)
    return domain in TEST_EMAIL_DOMAINS or bool(TEST_EMAIL_LOCAL.search(local))


def classify_existing(db: Session) -> dict:
    """One-time: flag pre-existing rows (is_test IS NULL). Returns counts."""
    users = db.query(models.User).filter(models.User.is_test.is_(None)).all()
    for u in users:
        u.is_test = is_test_email(u.email)
    db.flush()
    experts = db.query(models.ExpertProfile).filter(models.ExpertProfile.is_test.is_(None)).all()
    for e in experts:
        owner_test = bool(e.user and e.user.is_test)
        e.is_test = owner_test or (e.display_name or "").strip() in TEST_EXPERT_NAMES
        if e.is_test and e.user and not e.user.is_test:
            e.user.is_test = True
    db.commit()
    return {
        "users_classified": len(users),
        "experts_classified": len(experts),
        "hidden_users": db.query(models.User).filter(models.User.is_test.is_(True)).count(),
        "hidden_experts": db.query(models.ExpertProfile).filter(models.ExpertProfile.is_test.is_(True)).count(),
    }


def visible_expert():
    """SQLAlchemy filter: row is not marked is_test.

    This is not the catalog rule. Public discovery also hides reviewer-lane
    experts, and reviewers do not see real experts. Use can_discover_expert.
    """
    return or_(models.ExpertProfile.is_test.is_(None), models.ExpertProfile.is_test.is_(False))


def is_hidden(e: models.ExpertProfile | None) -> bool:
    return bool(e is not None and e.is_test)
