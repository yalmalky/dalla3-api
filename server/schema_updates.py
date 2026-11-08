"""Additive schema updates for the Apple reviewer lane.

Startup applies `upgrade_reviewer_schema`. It never backfills privileges from an
email domain. `downgrade_reviewer_schema` is the rollback and is not called on
startup. See docs/apple-reviewer-lane.md.
"""
from sqlalchemy import inspect
from sqlalchemy.engine import Engine


_ADDITIONS = (
    ("users", "is_apple_reviewer", "BOOLEAN NOT NULL DEFAULT 0"),
    ("bookings", "reviewer_lane", "BOOLEAN NOT NULL DEFAULT 0"),
)


def _columns(engine: Engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def upgrade_reviewer_schema(engine: Engine) -> list[str]:
    """Add reviewer columns when missing. Safe to run on every boot. Returns columns added."""
    added: list[str] = []
    for table, column, decl in _ADDITIONS:
        if column in _columns(engine, table):
            continue
        with engine.begin() as conn:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        added.append(f"{table}.{column}")
    return added


def downgrade_reviewer_schema(engine: Engine) -> list[str]:
    """Drop reviewer columns. SQLite 3.35+ and Postgres support DROP COLUMN."""
    removed: list[str] = []
    for table, column, _decl in reversed(_ADDITIONS):
        if column not in _columns(engine, table):
            continue
        with engine.begin() as conn:
            conn.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN {column}")
        removed.append(f"{table}.{column}")
    return removed
