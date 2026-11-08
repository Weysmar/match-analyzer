"""Spike of step 10, T10.2 and T10.3: are the touches believable, and does a Python detection from
the frames come close? Reads `out/<sha12>/` written by run_probe.py. Numbers only.

Checks, for each method:
- the scorer's team touched the ball within 10 s before each goal (the scorer, more strictly);
- no touch during a kickoff countdown;
- touches per minute of active play, per player.
The Python method is also compared with subtr-actor's touches: same player within ±3 frames.

Usage: uv run python spikes/s10-v2/check_touches.py
"""

import json
import statistics
import sys
from pathlib import Path

import numpy as np
import polars as pl

OUT = Path(__file__).resolve().parent / "out"
WINDOW_S = 10.0
MATCH_FRAMES = 3
COUNTDOWN, ACTIVE = 1, 3

# Python method: a jump of the ball's velocity with a car close by. Starting values, measured
# against subtr-actor below: ball radius 92.75, a car's half-length about 60, so centres within
# 260 uu can touch; 300 uu/s keeps bounces on the ground or walls out with the distance check.
PY_MIN_DV = 300.0
PY_MAX_DIST = 260.0
PY_COOLDOWN_FRAMES = 4


def per_frame(frames: pl.DataFrame) -> pl.DataFrame:
    return (
        frames.group_by("frame")
        .agg(
            pl.col("time_s").first(),
            pl.col("dt_s").first(),
            pl.col("phase").first(),
            pl.col(["ball_x", "ball_y", "ball_z", "ball_vx", "ball_vy", "ball_vz"]).first(),
        )
        .sort("frame")
    )


def python_touches(frames: pl.DataFrame, ball: pl.DataFrame) -> list[tuple[int, int]]:
    """(frame, player_idx) where the ball's velocity jumps with a car close enough to cause it."""
    v = ball.select("ball_vx", "ball_vy", "ball_vz").to_numpy()
    dv = np.linalg.norm(np.diff(v, axis=0), axis=1)
    candidates = ball["frame"].to_numpy()[1:][np.nan_to_num(dv) >= PY_MIN_DV]
    cars = frames.filter(pl.col("present") & ~pl.col("demolished")).select(
        "frame", "player_idx", "x", "y", "z"
    )
    by_frame = {f: g for f, g in cars.partition_by("frame", as_dict=True).items()}
    positions = dict(
        zip(ball["frame"].to_list(), ball.select("ball_x", "ball_y", "ball_z").rows(), strict=True)
    )
    found: list[tuple[int, int]] = []
    last: dict[int, int] = {}
    for frame in candidates:
        frame = int(frame)
        best = None
        for previous in (frame - 1, frame):
            group = by_frame.get((previous,))
            if group is None or positions.get(previous) is None or None in positions[previous]:
                continue
            bx, by, bz = positions[previous]
            xyz = group.select("x", "y", "z").to_numpy()
            dist = np.linalg.norm(xyz - np.array([bx, by, bz]), axis=1)
            k = int(np.nanargmin(dist)) if np.isfinite(dist).any() else -1
            if k >= 0 and dist[k] <= PY_MAX_DIST and (best is None or dist[k] < best[1]):
                best = (int(group["player_idx"][k]), float(dist[k]))
        if best is None:
            continue
        player = best[0]
        if frame - last.get(player, -100) < PY_COOLDOWN_FRAMES:
            continue
        last[player] = frame
        found.append((frame, player))
    return found


def check(name: str, touches: list[tuple[int, int, int]], goals: list[dict], ball: pl.DataFrame,
          totals: dict) -> None:
    """touches: (frame, player_idx, team)."""
    time_of = dict(zip(ball["frame"].to_list(), ball["time_s"].to_list(), strict=True))
    phase_of = dict(zip(ball["frame"].to_list(), ball["phase"].to_list(), strict=True))
    t = totals.setdefault(name, {"goals": 0, "team_touch": 0, "scorer_touch": 0,
                                 "countdown": 0, "touches": 0})
    for goal in goals:
        end = goal["time_s"]
        window = [
            (f, p, team) for f, p, team in touches
            if f <= goal["frame"] and end - time_of.get(f, -1e9) <= WINDOW_S
        ]
        t["goals"] += 1
        t["team_touch"] += any(team == goal["team"] for _, _, team in window)
        t["scorer_touch"] += any(p == goal["player_idx"] for _, p, _ in window)
    t["touches"] += len(touches)
    t["countdown"] += sum(phase_of.get(f) == COUNTDOWN for f, _, _ in touches)


def main() -> int:
    totals: dict = {}
    per_min: dict[str, list[float]] = {"subtr-actor": [], "python": []}
    agreement = {"subtr": 0, "python": 0, "matched": 0}
    replays = 0
    for folder in sorted(p for p in OUT.iterdir() if p.is_dir()):
        probe, events_path = folder / "probe.json", folder / "events.json"
        if not (probe.exists() and events_path.exists() and (folder / "frames.parquet").exists()):
            continue
        events = json.loads(events_path.read_text())
        roster_team = {m["player_idx"]: m["team"] for m in events["roster"]}
        frames = pl.read_parquet(folder / "frames.parquet")
        ball = per_frame(frames)
        found = json.loads(probe.read_text())["found"]
        subtr = [
            (int(e["frame"]), int(e["player"]["idx"]), 0 if e["is_team_0"] else 1)
            for e in found.get("touches", [])
            if isinstance(e.get("player"), dict)
        ]
        python = [(f, p, roster_team.get(p, -1)) for f, p in python_touches(frames, ball)]
        goals = [g for g in events["goals"] if g.get("player_idx") is not None]
        check("subtr-actor", subtr, goals, ball, totals)
        check("python", python, goals, ball, totals)
        active_min = ball.filter(pl.col("phase") == ACTIVE)["dt_s"].sum() / 60
        players = {m["player_idx"] for m in events["roster"]}
        if active_min > 1:
            for name, touches in (("subtr-actor", subtr), ("python", python)):
                for p in players:
                    per_min[name].append(sum(1 for _, q, _ in touches if q == p) / active_min)
        reference = {}
        for f, p, _ in subtr:
            reference.setdefault(p, []).append(f)
        agreement["subtr"] += len(subtr)
        agreement["python"] += len(python)
        agreement["matched"] += sum(
            any(abs(f - g) <= MATCH_FRAMES for g in reference.get(p, [])) for f, p, _ in python
        )
        replays += 1

    print(f"replays checked: {replays}")
    for name, t in totals.items():
        print(
            f"{name:12} touches {t['touches']:6}  goals {t['goals']}: team touch in 10 s "
            f"{t['team_touch'] / t['goals']:.1%}, scorer {t['scorer_touch'] / t['goals']:.1%}; "
            f"in countdown {t['countdown']}"
        )
    for name, values in per_min.items():
        q = statistics.quantiles(values, n=20)
        print(f"{name:12} touches/min per player: median {statistics.median(values):.1f}, "
              f"p5 {q[0]:.1f}, p95 {q[-1]:.1f}")
    a = agreement
    print(f"python vs subtr-actor (same player, ±{MATCH_FRAMES} frames): precision "
          f"{a['matched'] / a['python']:.1%}, recall {a['matched'] / a['subtr']:.1%} "
          f"({a['python']} vs {a['subtr']} touches)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
