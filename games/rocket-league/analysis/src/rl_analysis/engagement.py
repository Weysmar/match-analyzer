"""The engaged player (T14.2 of docs/PLAN-V2.md): one actually going for the ball, a definition the
rotation detectors share (double commits, then overcommits).

It is subtr-actor 1.5.1's commitment, from its beaten-to-ball detector
(stats/calculators/beaten_to_ball.rs), checked on every frame instead of only at an opponent's
touch. At a frame, over the last `ENGAGE_LOOKBACK` (1 s) of the player's motion:

- enough motion to judge: at least 4 samples covering 0.4 s;
- a sustained approach: the distance to the ball down by `ENGAGE_MIN_CLOSING` (200 uu), and closing
  on the ball in `ENGAGE_CLOSING_SHARE` (70 %) of the samples;
- heading for it: over the last 0.4 s, the velocity aligned with the ball by `ENGAGE_MIN_ALIGNMENT`
  (0.45) on average;
- committed: approaching at `ENGAGE_MIN_SPEED` (400 uu/s) on average over those 0.4 s, or a dodge
  while closing on the ball within the second;
- near: within `ENGAGE_MAX_DISTANCE` (1200 uu) of the ball.

subtr-actor measures from the car's hitbox; here, from its center, less the ball's radius. A car
away or demolished starts its history afresh when it comes back.
"""

import math
from collections import deque
from dataclasses import dataclass
from itertools import groupby

from rl_analysis.constants import Phase
from rl_analysis.match import Match
from rl_analysis.thresholds import (
    ENGAGE_CLOSING_SHARE,
    ENGAGE_LOOKBACK,
    ENGAGE_MAX_DISTANCE,
    ENGAGE_MIN_ALIGNMENT,
    ENGAGE_MIN_CLOSING,
    ENGAGE_MIN_SPEED,
)

BALL_RADIUS = 92.75
_MIN_SAMPLES = 4
_MIN_SPAN_S = 0.4
_RECENT_S = 0.4
_PHASES = (Phase.KICKOFF_WAITING, Phase.ACTIVE)


@dataclass(frozen=True)
class _Sample:
    time_s: float
    distance: float
    closing: float
    approach: float
    alignment: float
    dodge_toward: bool


def sample(
    time_s: float,
    car: tuple[float, float, float],
    velocity: tuple[float, float, float],
    ball: tuple[float, float, float],
    ball_velocity: tuple[float, float, float],
    dodged: bool,
) -> _Sample:
    """One frame of a car's motion relative to the ball."""
    to_ball = tuple(b - c for b, c in zip(ball, car, strict=True))
    length = math.sqrt(sum(d * d for d in to_ball)) or 1.0
    unit = tuple(d / length for d in to_ball)
    approach = sum(v * u for v, u in zip(velocity, unit, strict=True))
    closing = sum((v - w) * u for v, w, u in zip(velocity, ball_velocity, unit, strict=True))
    speed = math.sqrt(sum(v * v for v in velocity))
    return _Sample(
        time_s,
        max(0.0, length - BALL_RADIUS),
        closing,
        approach,
        approach / speed if speed > 0 else 0.0,
        dodged and closing > 0,
    )


def engaged(window: deque[_Sample]) -> bool:
    """Whether the last sample of `window` is an engaged frame, as described above."""
    if len(window) < _MIN_SAMPLES or window[-1].time_s - window[0].time_s < _MIN_SPAN_S:
        return False
    now = window[-1]
    if window[0].distance - now.distance < ENGAGE_MIN_CLOSING.value:
        return False
    if sum(s.closing > 0 for s in window) / len(window) < ENGAGE_CLOSING_SHARE.value:
        return False
    recent = [s for s in window if s.time_s >= now.time_s - _RECENT_S]
    if sum(s.alignment for s in recent) / len(recent) < ENGAGE_MIN_ALIGNMENT.value:
        return False
    fast = sum(s.approach for s in recent) / len(recent) >= ENGAGE_MIN_SPEED.value
    if not fast and not any(s.dodge_toward for s in window):
        return False
    return now.distance <= ENGAGE_MAX_DISTANCE.value


_COLUMNS = (
    "player_idx", "time_s", "phase", "present", "demolished", "x", "y", "z", "vx", "vy", "vz",
    "ball_x", "ball_y", "ball_z", "ball_vx", "ball_vy", "ball_vz", "dodged",
)  # fmt: skip


def resolve(match: Match) -> dict[int, list[tuple[float, bool]]]:
    """For each player, every frame of play they were on the field: its time and whether they were
    engaged. Live play and the kickoff wait only."""
    rows = match.frames.select(_COLUMNS).sort("player_idx", "time_s").iter_rows()
    found: dict[int, list[tuple[float, bool]]] = {}
    for player, grouped in groupby(rows, key=lambda row: row[0]):
        window: deque[_Sample] = deque()
        timeline: list[tuple[float, bool]] = []
        for row in grouped:
            _, time_s, phase, present, demolished = row[:5]
            values = row[5:17]
            if phase not in _PHASES or not present or demolished or None in values:
                window.clear()
                continue
            x, y, z, vx, vy, vz, bx, by, bz, bvx, bvy, bvz = (float(v) for v in values)
            window.append(
                sample(time_s, (x, y, z), (vx, vy, vz), (bx, by, bz), (bvx, bvy, bvz), row[17])
            )
            while window and window[0].time_s < time_s - ENGAGE_LOOKBACK.value:
                window.popleft()
            timeline.append((float(time_s), engaged(window)))
        found[int(player)] = timeline
    return found
