"""The 2D view's document of a match (T12.1 of docs/PLAN-V2.md, annex F)."""

from ma_db.sqlfile import run

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    run(__file__, "up")


def downgrade() -> None:
    run(__file__, "down")
