"""The rule deciding whether a match is verified."""

from ma_db.sqlfile import run

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    run(__file__, "up")


def downgrade() -> None:
    run(__file__, "down")
