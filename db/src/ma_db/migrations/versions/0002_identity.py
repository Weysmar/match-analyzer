"""Accounts, sessions and the identities players claim."""

from ma_db.sqlfile import run

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    run(__file__, "up")


def downgrade() -> None:
    run(__file__, "down")
