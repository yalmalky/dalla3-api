import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import Base, engine
from .routers import admin, auth_routes, bookings, catalog, expert_me, me, media
from .test_accounts import classify_existing
from .seed import ensure_promos
from .schema_updates import upgrade_reviewer_schema
from .db import SessionLocal


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    # Widen cover so photo data-URLs are not truncated at 500 chars
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE expert_profiles ALTER COLUMN cover TYPE TEXT"
            )
    except Exception:
        pass
    # BNPL surcharge column + float deposit/remaining for 2-decimal fees
    for sql in (
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS bnpl_surcharge DOUBLE PRECISION DEFAULT 0",
        "ALTER TABLE bookings ALTER COLUMN deposit TYPE DOUBLE PRECISION USING deposit::double precision",
        "ALTER TABLE bookings ALTER COLUMN remaining TYPE DOUBLE PRECISION USING remaining::double precision",
        "ALTER TABLE payment_ledger ALTER COLUMN amount TYPE DOUBLE PRECISION USING amount::double precision",
    ):
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(sql)
        except Exception:
            pass
    # Reversible test-account flag (portable: works on Postgres and SQLite)
    from sqlalchemy import inspect as _inspect
    for table in ("users", "expert_profiles"):
        cols = {c["name"] for c in _inspect(engine).get_columns(table)}
        if "is_test" not in cols:
            with engine.begin() as conn:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN is_test BOOLEAN")
    ucols = {c["name"] for c in _inspect(engine).get_columns("users")}
    for col in ("apple_sub", "google_sub"):
        if col not in ucols:
            with engine.begin() as conn:
                conn.exec_driver_sql(f"ALTER TABLE users ADD COLUMN {col} VARCHAR(255)")
    # Reviewer lane columns. No domain backfill — designation stays in APPLE_REVIEWER_EMAILS.
    upgrade_reviewer_schema(engine)
    db = SessionLocal()
    try:
        ensure_promos(db)
        print("test-account classification:", classify_existing(db), flush=True)
    finally:
        db.close()
    yield


app = FastAPI(title="Dalla3 API", version="0.1.0", lifespan=lifespan)
origins = get_settings().cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if origins == "*" else [o.strip() for o in origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(bookings.router, prefix="/api")
app.include_router(expert_me.router, prefix="/api")
app.include_router(me.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(media.router, prefix="/api")


@app.get("/health")
def health():
    return {"ok": True, "service": "dalla3-api", "payment": get_settings().payment_provider}


@app.get("/api/events/poll")
def poll_events(since: str | None = None, user_id: str | None = None):
    """Lightweight polling endpoint used by the app every few seconds.
    Push notifications skipped for family test (note in report).
    """
    # Actual notifications are fetched via /api/me/notifications; this keeps a stable URL for clients.
    return {"ok": True, "hint": "use /api/me/notifications? and /api/bookings"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), reload=False)
