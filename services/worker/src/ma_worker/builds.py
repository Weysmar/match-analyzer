"""How each build of the game fares with the parser (T9.9 of docs/PLAN.md): `ma-worker builds`, or
`just ops-builds`. A patch of the game can break the network stream while the header still reads
(section 5.3 of CLAUDE.md): its matches then end `header_only`, and this report shows it.

For each build seen over the last days: the matches whose network stream was tried, how many of
them it could not read, and when the build was first and last seen. A build is flagged when at
least `minimum` matches were tried and the share left `header_only` reaches `threshold`. Builds and
counts only: no match, no player.
"""

from dataclasses import dataclass
from datetime import datetime

from ma_worker.queue import Connection

# The network stream was tried: it read (parsed, then analyzed) or it did not (header_only).
_READ = ("parsed", "analyzing", "ready")
_UNREAD = "header_only"


@dataclass(frozen=True)
class BuildLine:
    build: str
    read: int
    unread: int
    first_seen: datetime
    last_seen: datetime

    @property
    def tried(self) -> int:
        return self.read + self.unread

    @property
    def unread_share(self) -> float | None:
        return self.unread / self.tried if self.tried else None

    def flagged(self, threshold: float, minimum: int) -> bool:
        share = self.unread_share
        return share is not None and self.tried >= minimum and share >= threshold


def fetch(connection: Connection, days: int) -> list[BuildLine]:
    """Every build seen over the last `days`, the latest seen first."""
    rows = connection.execute(
        """
        SELECT coalesce(game_build, 'unknown'),
               count(*) FILTER (WHERE status = ANY(%s)),
               count(*) FILTER (WHERE status = %s),
               min(created_at), max(created_at)
        FROM matches
        WHERE created_at >= now() - make_interval(days => %s)
        GROUP BY 1
        ORDER BY 5 DESC, 1
        """,
        (list(_READ), _UNREAD, days),
    ).fetchall()
    return [BuildLine(str(row[0]), int(row[1]), int(row[2]), row[3], row[4]) for row in rows]


def render(lines: list[BuildLine], threshold: float, minimum: int, days: int) -> str:
    """The report as text; the last line says whether a build looks broken."""
    if not lines:
        return f"no match over the last {days} day(s)"
    out = [f"builds seen over the last {days} day(s), latest first:"]
    for line in lines:
        share = "n/a" if line.unread_share is None else f"{100 * line.unread_share:.0f} %"
        mark = "  BROKEN?" if line.flagged(threshold, minimum) else ""
        out.append(
            f"  {line.build}: {line.tried} tried, {line.unread} header only ({share}); "
            f"seen {line.first_seen:%Y-%m-%d} to {line.last_seen:%Y-%m-%d}{mark}"
        )
    broken = [line.build for line in lines if line.flagged(threshold, minimum)]
    out.append(
        f"broken? {', '.join(broken)} (header only in {100 * threshold:.0f} % or more of "
        f"{minimum} matches or more): update boxcars and subtr-actor, then reprocess"
        if broken
        else "no build looks broken"
    )
    return "\n".join(out)
