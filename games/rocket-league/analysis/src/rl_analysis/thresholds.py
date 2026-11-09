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
