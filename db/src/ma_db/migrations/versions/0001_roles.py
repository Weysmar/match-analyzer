"""The roles the API and the worker connect with."""

from ma_db.sqlfile import run

revision = "0001"
down_revision = None


def upgrade() -> None:
    run(__file__, "up")


def downgrade() -> None:
    run(__file__, "down")
