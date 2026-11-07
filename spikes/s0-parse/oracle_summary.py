"""Hand-computed V1 metrics against subtr-actor's stats. The input holds no name and no id."""

import json
import statistics as st
import sys
from collections import Counter, defaultdict

rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
standard = [r for r in rows if r["map"] != "ShatterShot_P"]
print(f"replays: {len(rows)}, standard arena: {len(standard)}")

diffs = defaultdict(list)
values = defaultdict(list)
for r in standard:
    for player in r["players"]:
        for metric, (mine, theirs) in player.items():
            if metric == "pct_last_back" and r["team_size"] < 2:
                continue
            diffs[metric].append(abs(mine - theirs))
            values[metric].append(theirs)

signed = defaultdict(list)
mine_values = defaultdict(list)
for r in standard:
    for player in r["players"]:
        for metric, (mine, theirs) in player.items():
            if metric == "pct_last_back" and r["team_size"] < 2:
                continue
            signed[metric].append(mine - theirs)
            mine_values[metric].append(mine)

print(f"{'metric':<44}{'med |diff|':>11}{'p95 |diff|':>11}{'max':>9}{'med signed':>11}{'med mine':>10}{'med subtr':>10}")
for metric in sorted(diffs):
    d = sorted(diffs[metric])
    print(f"{metric:<44}{st.median(d):>11.3f}{d[int(.95 * len(d))]:>11.3f}{d[-1]:>9.2f}{st.median(signed[metric]):>11.3f}{st.median(mine_values[metric]):>10.2f}{st.median(values[metric]):>10.2f}")

outliers = 0
for r in standard:
    for player in r["players"]:
        mine, theirs = player["tracked_positioning_s"]
        if mine < 5 or theirs < 5:
            outliers += 1
print("\nplayers with under 5 s tracked:", outliers, "of", sum(len(r["players"]) for r in standard))

print("\nrespawn kinds:", dict(sum((Counter(r["respawn_kinds"]) for r in rows), Counter())))
durations = sorted(x for r in rows for x in r["demo_respawn_s"])
print("demolition to respawn, s:", {"n": len(durations), "median": round(st.median(durations), 2), "p5": round(durations[int(.05 * len(durations))], 2), "p95": round(durations[int(.95 * len(durations))], 2), "max": round(durations[-1], 2)} if durations else None)
print("demolitions without respawn:", sum(r["demo_without_respawn"] for r in rows))
car = [c for r in rows for c in r["demo_car"]]
if car:
    print("car during the window: distance median", round(st.median(c[0] for c in car), 1), " top speed median", round(st.median(c[1] for c in car), 1))
print("max dt in live play:", round(max(r["max_dt_active"] for r in rows), 3), " median of per-replay max:", round(st.median(r["max_dt_active"] for r in rows), 3))
print("pickup detection:", dict(sum((Counter(r["pickup_detection"]) for r in rows), Counter())))
