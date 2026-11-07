"""Uploads, and who owns which match."""

from ma_db.sqlfile import run

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    run(__file__, "up")


def downgrade() -> None:
    run(__file__, "down")
