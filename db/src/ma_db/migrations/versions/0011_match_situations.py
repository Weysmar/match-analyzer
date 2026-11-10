"""The situations of a match: what the detections found (T13.4 of docs/PLAN-V2.md, annex F)."""

from ma_db.sqlfile import run

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    run(__file__, "up")


def downgrade() -> None:
    run(__file__, "down")
