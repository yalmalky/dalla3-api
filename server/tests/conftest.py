"""Local sqlite only. This file overwrites DATABASE_URL before the app engine is created
so the suite cannot open a production database, even if the environment has one configured.
"""
import os

os.environ["DATABASE_URL"] = "sqlite:////tmp/dalla3-reviewer-lane-test.db"
os.environ["JWT_SECRET"] = "reviewer-lane-test-secret"
os.environ["PAYMENT_PROVIDER"] = "mock"
os.environ["APPLE_REVIEWER_EMAILS"] = (
    "apple-review-customer@dalla3.test,apple-review-expert@dalla3.test"
)
os.environ.pop("ADMIN_TOKEN", None)

db_path = "/tmp/dalla3-reviewer-lane-test.db"
if os.path.exists(db_path):
    os.remove(db_path)

import pytest
from fastapi.testclient import TestClient

from server.db import engine
from server.main import app


@pytest.fixture(scope="session")
def client():
    if engine.dialect.name != "sqlite":
        raise RuntimeError("Refusing to run reviewer-lane tests against a non-sqlite database")
    with TestClient(app) as test_client:
        yield test_client
