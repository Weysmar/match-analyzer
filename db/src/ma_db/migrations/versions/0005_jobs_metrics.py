"""The job queue, the metrics and the rate limits."""

from ma_db.sqlfile import run

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    run(__file__, "up")


def downgrade() -> None:
    run(__file__, "down")
