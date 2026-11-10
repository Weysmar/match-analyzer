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

# The first man is the closest to the ball only by more than this, on the ground plane: closer
# than that, who goes is ambiguous.
FIRST_MAN_MARGIN = Threshold(
    250.0,
    "uu",
    "subtr-actor 1.5.1, stats/calculators/rotation.rs, DEFAULT_FIRST_MAN_AMBIGUITY_MARGIN",
)

# A new first man only takes the role after holding it this long.
FIRST_MAN_DEBOUNCE = Threshold(
    0.35,
    "s",
    "subtr-actor 1.5.1, stats/calculators/rotation.rs, DEFAULT_FIRST_MAN_DEBOUNCE_SECONDS",
)

# The engaged player (T14.2): subtr-actor's commitment gates, from its beaten-to-ball detector.
_beaten = "subtr-actor 1.5.1, stats/calculators/beaten_to_ball.rs, BEATEN_TO_BALL_"
ENGAGE_LOOKBACK = Threshold(1.0, "s", _beaten + "LOOKBACK_SECONDS")
ENGAGE_MIN_CLOSING = Threshold(200.0, "uu", _beaten + "MIN_DISTANCE_DECREASE")
ENGAGE_CLOSING_SHARE = Threshold(0.7, "share", _beaten + "MIN_CLOSING_FRACTION")
ENGAGE_MIN_ALIGNMENT = Threshold(0.45, "cosine", _beaten + "MIN_VELOCITY_ALIGNMENT")
ENGAGE_MIN_SPEED = Threshold(400.0, "uu/s", _beaten + "MIN_APPROACH_SPEED")
ENGAGE_MAX_DISTANCE = Threshold(1200.0, "uu", _beaten + "MAX_DISTANCE_AT_TOUCH")

# Double commits (T14.3): the plan's starting values, to calibrate at step 17.
DOUBLE_COMMIT_MIN_OVERLAP = Threshold(
    0.25, "s", "convention of the plan, section 5.4: two engaged together at least this long"
)
DOUBLE_COMMIT_RESOLVE = Threshold(
    1.5, "s", "convention of the plan, section 5.4: a touch ends the sequence within this"
)
DOUBLE_COMMIT_PUNISH = Threshold(
    5.0, "s", "convention of the plan, section 5.4: an opponent shot or goal within this punishes"
)
KICKOFF_SCRAMBLE = Threshold(
    2.0, "s", "convention of the plan, section 5.4: going in two after a kickoff is a choice"
)

# How far apart a team's touches may be and still make one possession: the follow-up that confirms
# a loose ball taken, a possession kept, or a turnover. subtr-actor ties it to its loose-ball
# timeout, so that a player's possession never outlasts the team's.
POSSESSION_WINDOW = Threshold(
    3.0,
    "s",
    "subtr-actor 1.5.1, stats/calculators/possession.rs, POSSESSION_RESOLUTION_WINDOW_SECONDS",
)
