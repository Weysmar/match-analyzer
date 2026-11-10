"""The real-replay check of each metric (section 8.2 of CLAUDE.md): rl_analysis on the files that
`rl-parse` writes, against subtr-actor's own statistics through `rl-oracle`.

Only counts and differences are printed, never a name or an id.
"""

import hashlib
import json
import statistics
import subprocess
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from rl_analysis.boost import with_drops
from rl_analysis.constants import BOOST_RAW_MAX
from rl_analysis.frames import in_motion
from rl_analysis.match import Match, load
from rl_analysis.positioning import ahead_and_behind, thirds
from rl_analysis.registry import compute, compute_teams

pytestmark = pytest.mark.replays

ROOT = Path(__file__).parents[2]
RELEASE = ROOT / "games/rocket-league/parser/target/release"
REPLAYS = ROOT / "tests/fixtures/replays"
UNSUPPORTED_MODE = 14
RAW_TO_PERCENT = 100.0 / BOOST_RAW_MAX
# Written by `just oracle-cache` (tests/fixtures/oracle.py), keyed by the replay's hash.
ORACLE_CACHE = ROOT / "tests/fixtures/oracle/subtr-actor-1.5.1-format-4"
# What a car burns per second with boost held, as the spike measured it: 80 raw units per 0.93 s.
# Only used to check consumption, which never relies on it.
USE_RATE_PER_S = 80 / 0.93 * RAW_TO_PERCENT


def cached_oracle(replay: Path) -> Any:
    """subtr-actor's statistics for this replay: None when it could not read the replay."""
    path = ORACLE_CACHE / f"{hashlib.sha256(replay.read_bytes()).hexdigest()}.json"
    assert path.exists(), "run `just oracle-cache`"
    return json.loads(path.read_bytes())


def stat(oracle: dict[str, Any], module: str, name: str) -> float | None:
    stats = oracle.get(module)
    if not isinstance(stats, dict) or name not in stats:
        return None
    return float(stats[name])


def share(oracle: dict[str, Any], module: str, name: str, scale: float) -> float | None:
    """`name` over the module's tracked time, scaled. None when subtr-actor tracked nothing."""
    value, tracked = stat(oracle, module, name), stat(oracle, module, "tracked_time")
    if value is None or not tracked:
        return None
    return scale * value / tracked


def share_of(oracle: dict[str, Any], module: str, name: str, total: str) -> float | None:
    """`name` over `total` in the same module, in %. None when the total is 0."""
    value, whole = stat(oracle, module, name), stat(oracle, module, total)
    if value is None or not whole:
        return None
    return 100.0 * value / whole


def of_roles(oracle: dict[str, Any], name: str) -> float | None:
    """A role's share of the time with a role, ambiguous time left out, in %."""
    roles = [stat(oracle, "rotation", f"time_{role}_man") for role in ("first", "second", "third")]
    value = stat(oracle, "rotation", name)
    if value is None or None in roles or not sum(r for r in roles if r is not None):
        return None
    return 100.0 * value / sum(r for r in roles if r is not None)


def of_touches(oracle: dict[str, Any], name: str) -> float | None:
    """`name` as a share of the player's touches, in %. None without a touch."""
    value, touches = stat(oracle, "touch", name), stat(oracle, "touch", "touch_count")
    if value is None or not touches:
        return None
    return 100.0 * value / touches


# What subtr-actor says for each metric, in our units. Its boost is raw, from 0 to 255.
THEIRS: dict[str, Callable[[dict[str, Any]], float | None]] = {
    "boost.avg": lambda o: share(o, "boost", "boost_integral", RAW_TO_PERCENT),
    "boost.pct_zero": lambda o: share(o, "boost", "time_zero_boost", 100.0),
    "boost.pct_full": lambda o: share(o, "boost", "time_hundred_boost", 100.0),
    "boost.pads_big": lambda o: stat(o, "boost", "big_pads_collected"),
    "boost.pads_small": lambda o: stat(o, "boost", "small_pads_collected"),
    "move.speed_avg": lambda o: share(o, "movement", "speed_integral", 1.0),
    "move.pct_supersonic": lambda o: share(o, "movement", "time_supersonic_speed", 100.0),
    "move.pct_ground": lambda o: share(o, "movement", "time_on_ground", 100.0),
    "move.pct_low_air": lambda o: share(o, "movement", "time_low_air", 100.0),
    "move.pct_high_air": lambda o: share(o, "movement", "time_high_air", 100.0),
    "pos.dist_ball_avg": lambda o: share(o, "positioning", "sum_distance_to_ball", 1.0),
    "pos.pct_last_back": lambda o: share(o, "positioning", "time_most_back", 100.0),
    "event.demos_inflicted": lambda o: stat(o, "demo", "demos_inflicted"),
    "event.demos_taken": lambda o: stat(o, "demo", "demos_taken"),
    "touch.count": lambda o: stat(o, "touch", "touch_count"),
    "touch.pct_hard": lambda o: of_touches(o, "hard_hit_count"),
    "touch.pct_aerial": lambda o: of_touches(o, "high_aerial_touch_count"),
    # Kickoffs where the player made the team's kickoff touch.
    "kick.taken": lambda o: stat(o, "kickoff", "touches"),
    "duel.count": lambda o: stat(o, "fifty_fifty", "count"),
    # The share with the ball afterwards, as the plan defines a duel won.
    "duel.won_pct": lambda o: share_of(o, "fifty_fifty", "possession_after_count", "count"),
    "rot.pct_first": lambda o: of_roles(o, "time_first_man"),
    "rot.pct_second": lambda o: of_roles(o, "time_second_man"),
    "rot.pct_third": lambda o: of_roles(o, "time_third_man"),
}

# The plan's thirds and its ahead / behind differ from subtr-actor's on purpose (D4, no margin).
# Computed with subtr-actor's settings instead, they check the computation itself, as the spike did.
SUBTR_THIRD_CUT = 2300.0
SUBTR_BALL_MARGIN = 150.0

# Bounds on the median and the 95th percentile of the absolute difference. They come from the
# spike's measures (section 7 of its report) with a margin, and from the plan's criteria: T7.5 asks
# for a median of 0 and a 95th percentile of at most 4 big and 5 small pads.
#
# Like the spike, the comparison keeps the current replay format (`net` 10 or more): 5 replays of
# the corpus are older. On two of them, from 2016, subtr-actor's boost module tracks a player 30 to
# 69 s less than its own movement and positioning modules do, which both match our reference time
# exactly: the reference is off there, not the metric. Players upload the current format.
CURRENT_FORMAT_NET = 10
BOUNDS = {
    "boost.avg": (0.02, 0.1),
    "boost.pct_zero": (0.3, 1.5),
    "boost.pct_full": (0.3, 0.5),
    "boost.pads_big": (0.0, 4.0),
    "boost.pads_small": (0.0, 5.0),
    "move.speed_avg": (0.5, 5.0),
    "move.pct_supersonic": (0.05, 0.2),
    "move.pct_ground": (0.05, 0.3),
    "move.pct_low_air": (0.05, 0.3),
    "move.pct_high_air": (0.05, 0.3),
    # The spike: 0.004 uu at the median, 65 uu at the 95th percentile.
    "pos.dist_ball_avg": (0.1, 80.0),
    # A definition of our own, without subtr-actor's role logic (T7.10): the spike measured 4.4 and
    # 7.8 points. Documented, not corrected (D8).
    "pos.pct_last_back": (6.0, 12.0),
    "event.demos_inflicted": (0.0, 0.0),
    "event.demos_taken": (0.0, 0.0),
    # With subtr-actor's settings; the spike: 0.04 / 0.83 point for the thirds, 0.05 / 0.46 for
    # ahead and behind.
    "pos.thirds_at_2300": (0.1, 1.0),
    "pos.ahead_behind_with_margin": (0.1, 0.6),
    # The touches are subtr-actor's own (DV1), through rl-parse: equal for every player.
    "touch.count": (0.0, 0.0),
    "touch.pct_hard": (0.0, 0.0),
    "touch.pct_aerial": (0.0, 0.0),
    # Its PossessionResolver, ported (B7): 0.002 point at the median, 1.24 at the 95th
    # percentile on the whole local corpus, 1.53 on the 26 public replays alone. The gaps are
    # all the last segment of a replay that ends in live play, which its statistics count as a
    # loose ball, its events give to the holder up to the end, and we stop at the last touch (B10):
    # up to 8.9 points on a long final possession.
    "poss.team_pct": (0.05, 2.0),
    # Not the same definition: subtr-actor's player possession comes from its eager tracker,
    # ours splits the team's resolved possession between its touchers (B7). Measured: 4.3 and 9.4
    # points locally, 5.2 and 9.7 on the public replays. Documented, not corrected, like the last
    # back.
    "poss.player_pct": (6.0, 11.0),
    # Ours is the first of the team to touch the ball within 6 s of the countdown, theirs the
    # taker they designate who touched: the same player in 97 % of the team kickoffs (B16).
    # Measured: 0 at the median, 2 at the 95th percentile, 3 at most.
    "kick.taken": (0.0, 3.0),
    # subtr-actor's own detector, read as it is: equal for every player (B17).
    "duel.count": (0.0, 0.0),
    "duel.won_pct": (0.0, 0.0),
    # Its RotationCalculator, ported (B19): 0.2 point at the median, 0.8 to 1.0 at the 95th
    # percentile. The rest: our demolition window and team size, read from the frames, where it
    # reads its own demolitions and the game's replicated team size.
    "rot.pct_first": (0.5, 2.0),
    "rot.pct_second": (0.5, 2.0),
    "rot.pct_third": (0.5, 2.0),
}
# Consumption is checked against two other ways of counting it, as relative differences (T7.4).
CONSUMPTION_BOUND = 0.05


@dataclass
class Corpus:
    differences: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    consumption: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    band_sums: list[float] = field(default_factory=list)
    replays: int = 0
    skipped: int = 0
    old_format: int = 0
    teams_mismatched: int = 0


def distinct_replays() -> list[Path]:
    seen: dict[bytes, Path] = {}
    for path in sorted(REPLAYS.rglob("*.replay")):
        seen.setdefault(path.read_bytes()[:4096] + str(path.stat().st_size).encode(), path)
    return list(seen.values())


def relative(mine: float, theirs: float) -> float | None:
    return abs(mine - theirs) / theirs if theirs > 0 else None


def check_consumption(corpus: Corpus, match: Match, theirs: dict[int, dict[str, Any]]) -> None:
    """T7.4: the falls of the boost against `boost_active` times the rate, on the same time; and,
    counted on every frame, against subtr-actor's `amount_used`, which counts them all (A5)."""
    frames = with_drops(match.frames)
    kept = in_motion() & pl.col("boost").is_not_null()
    sums = frames.group_by("player_idx").agg(
        pl.when(kept).then(pl.col("drop")).otherwise(0.0).sum().alias("falls"),
        pl.when(kept & pl.col("boost_active"))
        .then(pl.col("dt_s") * USE_RATE_PER_S)
        .otherwise(0.0)
        .sum()
        .alias("by_rate"),
        pl.when(pl.col("present")).then(pl.col("drop")).otherwise(0.0).sum().alias("all_falls"),
    )
    for player, falls, by_rate, all_falls in sums.select(
        "player_idx", "falls", "by_rate", "all_falls"
    ).rows():
        if (difference := relative(falls, by_rate)) is not None:
            corpus.consumption["against the rate"].append(difference)
        used = stat(theirs[player], "boost", "amount_used")
        if used is not None and (difference := relative(all_falls, used * RAW_TO_PERCENT)):
            corpus.consumption["every frame, against amount_used"].append(difference)


def check_with_subtr_settings(
    corpus: Corpus, match: Match, theirs: dict[int, dict[str, Any]]
) -> None:
    pairs = list(
        zip(
            thirds(match, SUBTR_THIRD_CUT),
            ["time_defensive_third", "time_neutral_third", "time_offensive_third"],
            strict=True,
        )
    )
    for values, name in pairs:
        for player, mine in values.items():
            expected = share(theirs[player], "positioning", name, 100.0)
            if mine is not None and expected is not None:
                corpus.differences["pos.thirds_at_2300"].append(abs(mine - expected))
    ahead, behind = ahead_and_behind(match, SUBTR_BALL_MARGIN)
    for values, name in ((ahead, "time_in_front_of_ball"), (behind, "time_behind_ball")):
        for player, mine in values.items():
            expected = share(theirs[player], "positioning", name, 100.0)
            if mine is not None and expected is not None:
                corpus.differences["pos.ahead_behind_with_margin"].append(abs(mine - expected))


def check_possession(
    corpus: Corpus, match: Match, oracle: dict[str, Any], theirs: dict[int, dict[str, Any]]
) -> None:
    """The team share against subtr-actor's possession stats; the player share against its
    player possession spans, over the same tracked time."""
    tracked = stat(oracle, "possession", "tracked_time")
    if not tracked:
        return
    names = {0: "team_zero_time", 1: "team_one_time"}
    for team, values in compute_teams(match).items():
        mine, held = values["poss.team_pct"], stat(oracle, "possession", names[team])
        if mine is not None and held is not None:
            corpus.differences["poss.team_pct"].append(abs(mine - 100.0 * held / tracked))
    for player, values in compute(match).items():
        mine, spans = values["poss.player_pct"], theirs[player].get("player_possession")
        if mine is not None and isinstance(spans, dict):
            expected = 100.0 * float(spans["time"]) / tracked
            corpus.differences["poss.player_pct"].append(abs(mine - expected))


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Corpus:
    found = Corpus()
    for replay in distinct_replays():
        folder = tmp_path_factory.mktemp("frames")
        parsed = subprocess.run(
            [RELEASE / "rl-parse", "--frames", "--input", replay, "--output-dir", folder],
            capture_output=True,
        )
        if parsed.returncode == UNSUPPORTED_MODE:
            continue
        assert parsed.returncode == 0
        header_path = folder / "header.json"
        subprocess.run(
            [RELEASE / "rl-parse", "--header", "--input", replay, "--output", header_path],
            check=True,
            capture_output=True,
        )
        net = json.loads(header_path.read_text(encoding="utf-8"))["replay_version"]["net"]
        if net is None or net < CURRENT_FORMAT_NET:
            found.old_format += 1
            continue
        oracle = cached_oracle(replay)
        if oracle is None:
            found.skipped += 1
            continue
        found.replays += 1
        theirs = {row["player_idx"]: row for row in oracle["players"]}
        match = load(folder / "frames.parquet", folder / "events.json")
        found.teams_mismatched += sum(
            theirs[member["player_idx"]]["team"] != member["team"]
            for member in match.events["roster"]
        )
        check_consumption(found, match, theirs)
        check_with_subtr_settings(found, match, theirs)
        check_possession(found, match, oracle, theirs)
        for player, values in compute(match).items():
            bands = [values[band] for band in ("move.pct_ground", "move.pct_low_air")]
            bands.append(values["move.pct_high_air"])
            if None not in bands:
                found.band_sums.append(sum(band for band in bands if band is not None))
            for metric_id, mine in values.items():
                if metric_id not in THEIRS:
                    continue
                expected = THEIRS[metric_id](theirs[player])
                if mine is not None and expected is not None:
                    found.differences[metric_id].append(abs(mine - expected))
    return found


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[int(0.95 * (len(ordered) - 1))]


def test_the_oracle_lines_up_with_the_roster(corpus: Corpus) -> None:
    """Same players in the same order: otherwise every comparison below would be meaningless."""
    assert corpus.replays > 0
    assert corpus.teams_mismatched == 0


@pytest.mark.parametrize("metric_id", sorted(BOUNDS))
def test_a_metric_agrees_with_subtr_actor(
    corpus: Corpus, metric_id: str, capsys: pytest.CaptureFixture[str]
) -> None:
    found = sorted(corpus.differences[metric_id])
    assert found
    median, p95 = statistics.median(found), percentile_95(found)
    with capsys.disabled():
        print(
            f"\n{metric_id}: {len(found)} players in {corpus.replays} replays "
            f"({corpus.skipped} unread by subtr-actor, {corpus.old_format} of an old format "
            f"left out), |diff| median {median:.4f}, p95 {p95:.4f}, max {found[-1]:.4f}"
        )
    median_bound, p95_bound = BOUNDS[metric_id]
    assert median <= median_bound
    assert p95 <= p95_bound


@pytest.mark.parametrize("check", ["against the rate", "every frame, against amount_used"])
def test_consumption_agrees_with_other_ways_of_counting(
    corpus: Corpus, check: str, capsys: pytest.CaptureFixture[str]
) -> None:
    found = corpus.consumption[check]
    assert found
    median = statistics.median(found)
    with capsys.disabled():
        print(
            f"\nboost.used_per_min, {check}: {len(found)} players, relative difference "
            f"median {100 * median:.2f} %, p95 {100 * percentile_95(found):.2f} %"
        )
    assert median < CONSUMPTION_BOUND


def test_the_altitude_bands_add_up_to_the_whole_time(corpus: Corpus) -> None:
    """T7.7: 100 % within 0.1."""
    assert corpus.band_sums
    assert all(abs(total - 100.0) <= 0.1 for total in corpus.band_sums)


def test_the_cache_names_the_subtr_actor_in_use() -> None:
    """The cache's folder, and tests/fixtures/oracle.py, which builds it, name
    subtr-actor's version and rl-oracle's output format: a new one has to start afresh."""
    cargo = (ROOT / "games/rocket-league/parser/Cargo.toml").read_text(encoding="utf-8")
    oracle = (ROOT / "tests/fixtures/oracle.py").read_text(encoding="utf-8")
    version, output_format = ORACLE_CACHE.name.removeprefix("subtr-actor-").split("-format-")
    assert f'subtr-actor = "={version}"' in cargo
    assert f'SUBTR_ACTOR = "{version}"' in oracle
    assert f"OUTPUT_FORMAT = {output_format}" in oracle
