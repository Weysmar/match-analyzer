"""Matches, the players in them and what happened."""

from ma_db.sqlfile import run

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    run(__file__, "up")


def downgrade() -> None:
    run(__file__, "down")
