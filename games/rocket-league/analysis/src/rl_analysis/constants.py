"""The numbers the metrics rest on. Each one says where it comes from: a measure on real replays
(`spikes/s0-parse/RAPPORT.md`, section 6 unless said otherwise), a decision of the plan, or a
convention when the data cannot settle it.

All lengths are in Unreal units (uu).
"""

from enum import IntEnum

# The standard arena. Measured: cars reach x = ±4094, the ceiling sits at z ≈ 2044 (cars 2039).
FIELD_HALF_WIDTH = 4096.0
FIELD_HALF_LENGTH = 5120.0
CEILING_Z = 2044.0
# Inside the goals, out of the field above. Measured: cars to |y| ≈ 5991, the ball to ≈ 5215.
GOAL_DEPTH_CARS_Y = 5991.0

# Thirds of the field, along y relative to the team. Decision D4: true thirds of the field, where
# subtr-actor cuts at ±2300. Measured effect: 43.5 / 33.3 / 22.6 % instead of 37.8 / 43.4 / 17.8 %.
THIRD_Y = FIELD_HALF_LENGTH / 3

# Speeds. Measured: a sharp plateau at exactly 2300.
MAX_CAR_SPEED = 2300.0
# A convention, not a measure (A11): the speed distribution shows no break at 2200, so the data
# cannot confirm it. Kept because the game's own notion of supersonic sits there.
SUPERSONIC_SPEED = 2200.0

# Altitude bands, decision D7. Measured: a car on the ground sits at z = 17 (median), so 20 is safe.
# High air starts where a car could no longer touch a ball resting on the ground, as subtr-actor
# has it. Driving on a wall counts as air: there is no `on_ground` in the data.
BALL_RADIUS = 92.75
GROUND_MAX_Z = 20.0
HIGH_AIR_MIN_Z = 642.775 + BALL_RADIUS

# Boost, from 0 to 100 in the frames: `rl-parse` normalizes the replay's 0 to 255. Measured: 85 raw
# at every kickoff (95 replays out of 95). Empty and full are one raw unit from the ends, as the
# float can land a hair off the exact value.
BOOST_RAW_MAX = 255.0
BOOST_ZERO_MAX = 100.0 * 1 / BOOST_RAW_MAX
BOOST_FULL_MIN = 100.0 * 254 / BOOST_RAW_MAX

# Pads come back after 10 s (big) and 4 s (small). `rl-parse` already uses these to deduplicate
# pickups (A18); they are here for the record.
BIG_PAD_RESPAWN_S = 10.0
SMALL_PAD_RESPAWN_S = 4.0

# The blue team (0) defends y < 0. Measured: 91 kickoffs out of 91, and 306 blue goals out of 308
# scored at y > 0.
BLUE_TEAM = 0
ORANGE_TEAM = 1


class Phase(IntEnum):
    """The `phase` column of `frames.parquet`."""

    UNKNOWN = 0
    COUNTDOWN = 1
    KICKOFF_WAITING = 2
    ACTIVE = 3
    AFTER_GOAL = 4


# Reference time (D16), as the spike validated against subtr-actor: kickoff waiting and live play
# for boost and movement, live play alone for positioning. Countdowns and the time after a goal are
# always out, and so is a demolished car.
MOTION_PHASES = (Phase.KICKOFF_WAITING, Phase.ACTIVE)
LIVE_PHASES = (Phase.ACTIVE,)
