"""Runs the SQL file next to a migration: migrations stay plain, versioned SQL."""

from pathlib import Path

from alembic import op


def run(migration: str, direction: str) -> None:
    """Runs `<migration>.<direction>.sql`, `direction` being `up` or `down`."""
    sql = Path(migration).with_suffix(f".{direction}.sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)
