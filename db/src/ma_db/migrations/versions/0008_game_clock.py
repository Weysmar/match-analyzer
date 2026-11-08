"""The game clock, worked out by the analysis: match length, overtime and the time of each goal."""

from ma_db.sqlfile import run

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    run(__file__, "up")


def downgrade() -> None:
    run(__file__, "down")
