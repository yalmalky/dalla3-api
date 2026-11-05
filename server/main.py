import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import Base, engine
from .routers import auth_routes, bookings, catalog, expert_me, me
from .seed import ensure_promos
from .db import SessionLocal


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_promos(db)
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
