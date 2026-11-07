"""Applying memorized players to an owner's matches."""

from ma_db.sqlfile import run

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    run(__file__, "up")


def downgrade() -> None:
    run(__file__, "down")
