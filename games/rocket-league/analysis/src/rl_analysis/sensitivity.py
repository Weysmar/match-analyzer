"""How much each detector's count moves when one of its thresholds does (section 4, rule 5 of
docs/PLAN-V2.md): every threshold of a detector is set 20 % lower, then 20 % higher, one at a time,
and the detector counted again on the same matches. A detector whose count moves by more than half
for one of them is fragile, and the report says so.

Only the detectors with thresholds of their own are measured: turnovers, double commits and
overcommits. Kickoffs and duels are subtr-actor's, read from the parser as they are.
"""

import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace

from rl_analysis import commits, overcommits, possession, thresholds
from rl_analysis.match import Match

FACTORS = (0.8, 1.2)
FRAGILE = 0.5


def _turnovers(match: Match) -> int:
    resolved = possession.resolve(match)
    return 0 if resolved is None else len(resolved.turnovers)


def _double_commits(match: Match) -> int:
    return len(commits.resolve(match) or [])


def _overcommits(match: Match) -> int:
    return len(overcommits.resolve(match) or [])


ENGAGE = [
    "ENGAGE_LOOKBACK",
    "ENGAGE_MIN_CLOSING",
    "ENGAGE_CLOSING_SHARE",
    "ENGAGE_MIN_ALIGNMENT",
    "ENGAGE_MIN_SPEED",
    "ENGAGE_MAX_DISTANCE",
]
DETECTORS: dict[str, tuple[Callable[[Match], int], list[str]]] = {
    "turnover": (_turnovers, ["POSSESSION_WINDOW"]),
    "double_commit": (
        _double_commits,
        [*ENGAGE, "DOUBLE_COMMIT_MIN_OVERLAP", "DOUBLE_COMMIT_RESOLVE", "KICKOFF_SCRAMBLE"],
    ),
    "overcommit": (_overcommits, ["OVERCOMMIT_MARGIN", "OVERCOMMIT_MIN", "POSSESSION_WINDOW"]),
}


@contextmanager
def varied(name: str, factor: float) -> Iterator[None]:
    """The threshold `name` multiplied by `factor` wherever the analysis imported it, then put back.
    The detectors import thresholds by name: each binding has to change."""
    original = getattr(thresholds, name)
    changed = replace(original, value=original.value * factor)
    bound = [
        module
        for module_name, module in list(sys.modules.items())
        if module_name.startswith("rl_analysis") and getattr(module, name, None) is original
    ]
    for module in bound:
        setattr(module, name, changed)
    try:
        yield
    finally:
        for module in bound:
            setattr(module, name, original)


@dataclass(frozen=True)
class Row:
    detector: str
    threshold: str
    base: int
    # The count at each factor of FACTORS.
    counts: tuple[int, ...]

    @property
    def largest_change(self) -> float:
        """The largest relative move of the count, against the base: 0.6 is 60 %."""
        if self.base == 0:
            return 0.0 if all(count == 0 for count in self.counts) else float("inf")
        return max(abs(count - self.base) / self.base for count in self.counts)

    @property
    def fragile(self) -> bool:
        return self.largest_change > FRAGILE


def measure(matches: list[Match]) -> list[Row]:
    """Every detector, every threshold of it, at each factor, summed over the matches."""
    rows = []
    for detector, (count, names) in DETECTORS.items():
        base = sum(count(match) for match in matches)
        for name in names:
            counts = []
            for factor in FACTORS:
                with varied(name, factor):
                    counts.append(sum(count(match) for match in matches))
            rows.append(Row(detector, name, base, tuple(counts)))
    return rows


def render(rows: list[Row], matches: int) -> str:
    """The sensitivity as text: counts and percentages only."""
    lines = [f"sensitivity, thresholds at -20 % and +20 %, over {matches} match(es):"]
    for row in rows:
        low, high = row.counts
        change = (
            "n/a" if row.largest_change == float("inf") else f"{100 * row.largest_change:.0f} %"
        )
        flag = "  FRAGILE" if row.fragile else ""
        lines.append(
            f"  {row.detector} / {row.threshold}: {row.base} -> {low} (-20 %), {high} (+20 %); "
            f"largest move {change}{flag}"
        )
    fragile = sorted({row.detector for row in rows if row.fragile})
    lines.append("fragile: " + (", ".join(fragile) if fragile else "none"))
    return "\n".join(lines)
