"""Additive schema updates for the Apple reviewer lane.

Startup applies `upgrade_reviewer_schema`. It never grants the lane from an
email or from existing rows. `downgrade_reviewer_schema` is the rollback and
is not called on startup. See docs/apple-reviewer-lane.md.
"""
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from .models import active_slot_index_predicate


_ADDITIONS = (
    ("users", "is_apple_reviewer"),
    ("bookings", "reviewer_lane"),
)
_SLOT_INDEX = "uq_booking_active_slot"


def _boolean_column(engine: Engine) -> str:
    # Postgres rejects DEFAULT 0 for boolean. SQLite accepts 0; both mean false.
    literal = "FALSE" if engine.dialect.name == "postgresql" else "0"
    return f"BOOLEAN NOT NULL DEFAULT {literal}"


def _columns(engine: Engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def _index_names(engine: Engine, table: str) -> set[str]:
    return {idx["name"] for idx in inspect(engine).get_indexes(table)}


def upgrade_reviewer_schema(engine: Engine) -> list[str]:
    """Add reviewer columns and the active-slot index when missing.

    Does not update or delete existing rows. Raises if duplicate active slots
    already exist, leaving those bookings unchanged.
    """
    added: list[str] = []
    decl = _boolean_column(engine)
    for table, column in _ADDITIONS:
        if column in _columns(engine, table):
            continue
        with engine.begin() as conn:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        added.append(f"{table}.{column}")
    if _SLOT_INDEX not in _index_names(engine, "bookings"):
        where = active_slot_index_predicate()
        with engine.begin() as conn:
            conn.exec_driver_sql(
                f"CREATE UNIQUE INDEX {_SLOT_INDEX} ON bookings (expert_id, date, time) WHERE {where}"
            )
        added.append(f"bookings.{_SLOT_INDEX}")
    return added


def downgrade_reviewer_schema(engine: Engine) -> list[str]:
    """Drop the slot index and reviewer columns. SQLite 3.35+ and Postgres support DROP COLUMN."""
    removed: list[str] = []
    if _SLOT_INDEX in _index_names(engine, "bookings"):
        with engine.begin() as conn:
            conn.exec_driver_sql(f"DROP INDEX IF EXISTS {_SLOT_INDEX}")
        removed.append(f"bookings.{_SLOT_INDEX}")
    for table, column in reversed(_ADDITIONS):
        if column not in _columns(engine, table):
            continue
        with engine.begin() as conn:
            conn.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN {column}")
        removed.append(f"{table}.{column}")
    return removed
