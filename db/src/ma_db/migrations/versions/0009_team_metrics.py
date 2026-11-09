"""The team metrics of V2: possession first (T11.5 of docs/PLAN-V2.md, annex F)."""

from ma_db.sqlfile import run

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    run(__file__, "up")


def downgrade() -> None:
    run(__file__, "down")
