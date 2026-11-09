"""The thresholds of the V2 detections (section 4 of docs/PLAN-V2.md).

A threshold turns a measure into a fact, so each one says where it comes from, in this order of
preference:

- `measured`: a measure on the corpus, with its figure;
- `subtr-actor`: the default of subtr-actor 1.5.1, our reference, with its file and constant;
- `convention`: when neither settles it, said as such.

A test refuses a threshold without one of these sources. Changing a value moves ANALYSIS_VERSION on.
The V1 constants (field, altitude bands, boost) stay in `constants.py`, measured at step 0.
"""

from dataclasses import dataclass

SOURCES = ("measured", "subtr-actor", "convention")


@dataclass(frozen=True)
class Threshold:
    value: float
    unit: str
    source: str


# A touch that changes the ball's speed this much is a hard hit, as subtr-actor tags it.
HARD_TOUCH_SPEED_CHANGE = Threshold(
    900.0,
    "uu/s",
    "subtr-actor 1.5.1, stats/calculators/touch.rs, HARD_TOUCH_BALL_SPEED_CHANGE_THRESHOLD",
)

# How long after the countdown a team's first touch still makes it the kickoff's taker. Measured
# on the 1373 team kickoffs of the corpus with a touch: p95 3.39 s, p99 5.28 s, 99.6 % within
# 6 s; the 6 beyond, from 8 to 352 s, are outliers of subtr-actor's kickoff window.
KICKOFF_TOUCH_MAX = Threshold(
    6.0,
    "s",
    "measured on the corpus, first touches of each team after the countdown: 99.6 % within 6 s",
)

# How far apart a team's touches may be and still make one possession: the follow-up that confirms
# a loose ball taken, a possession kept, or a turnover. subtr-actor ties it to its loose-ball
# timeout, so that a player's possession never outlasts the team's.
POSSESSION_WINDOW = Threshold(
    3.0,
    "s",
    "subtr-actor 1.5.1, stats/calculators/possession.rs, POSSESSION_RESOLUTION_WINDOW_SECONDS",
)
