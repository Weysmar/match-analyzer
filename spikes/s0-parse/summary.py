"""Summary of the step 0 spike. Measurements only: the input holds no player name and no id."""

import json
import statistics as st
import sys
from collections import Counter, defaultdict


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def era(r):
    h = r.get("header") or {}
    v = h.get("version") or [None, None, None]
    build = h.get("build_version") or "?"
    return v[2], build


rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
print(f"replays: {len(rows)}")
print("by group:", dict(Counter(r["group"] for r in rows)))
print("killed by timeout:", sum(r["killed_by_timeout"] for r in rows), " exit != 0:", sum(r["exit"] != 0 for r in rows))

print("\n== parsing by group ==")
for group in sorted({r["group"] for r in rows}):
    g = [r for r in rows if r["group"] == group]
    print(group, {k: f"{sum(bool(r.get(k)) for r in g)}/{len(g)}" for k in ("header_ok", "network_ok", "data_ok", "phases_ok", "stats_ok")})

print("\n== failures ==")
for r in rows:
    for k in ("header_error", "network_error", "data_error", "phases_error"):
        if r.get(k):
            print(r["group"], r["file"], k, r[k])
    if not r.get("stats_ok") and r.get("data_ok"):
        print(r["group"], r["file"], "stats failed")

print("\n== by replay/net version ==")
by = defaultdict(list)
for r in rows:
    v = (r.get("header") or {}).get("version")
    by[tuple(v) if v else None].append(r)
for v in sorted(by, key=lambda x: (x is None, str(x))):
    g = by[v]
    print(v, "n=", len(g), {k: sum(bool(r.get(k)) for r in g) for k in ("network_ok", "data_ok", "phases_ok")})

recent = [r for r in rows if r.get("data_ok") and (r["header"]["version"][2] or 0) >= 10]

print("\n== header facts ==")
for label, select in (("net>=11", lambda r: (r["header"]["version"][2] or 0) >= 11), ("net<11", lambda r: (r["header"]["version"][2] or 0) < 11)):
    g = [r for r in rows if r.get("header_ok") and select(r)]
    if not g:
        continue
    print(label, "n=", len(g), "MatchGUID", sum(r["header"]["has_match_guid"] for r in g), "epoch", sum(r["header"]["match_start_epoch"] is not None for r in g), "Id", sum(r["header"]["has_id"] for r in g))
goal_keys, player_keys = Counter(), Counter()
platform_zero = defaultdict(Counter)
for r in rows:
    h = r.get("header")
    if not h:
        continue
    goal_keys.update(h["goal_keys"])
    player_keys.update(h["player_keys"])
    for p in h["players"]:
        platform_zero[p["platform"]][("bot" if p["bot"] else "human", "id_zero" if p["online_id_zero"] else "id_set")] += 1
print("goal keys:", dict(goal_keys))
print("player keys:", dict(player_keys))
print("OnlineID by platform:", {k: {str(a): b for a, b in v.items()} for k, v in platform_zero.items()})
print("record_fps:", Counter((r.get("header") or {}).get("record_fps") for r in rows))
print("match types:", Counter((r.get("header") or {}).get("match_type") for r in rows))
print("classes:", Counter((r.get("header") or {}).get("class") for r in rows))
offsets = []
for r in rows:
    h = r.get("header") or {}
    if h.get("match_start_epoch") and h.get("date"):
        offsets.append(r)
print("epoch sample (value magnitude):", [len(str(r["header"]["match_start_epoch"])) for r in offsets[:5]])
import datetime as dt
diffs = Counter()
for r in offsets:
    h = r["header"]
    e = h["match_start_epoch"]
    e = e / 1000 if e > 10**11 else e
    d = dt.datetime.strptime(h["date"], "%Y-%m-%d %H-%M-%S").replace(tzinfo=dt.timezone.utc)
    diffs[round((d.timestamp() - e) / 900) / 4] += 1
print("Date - MatchStartEpoch, in hours (rounded to 15 min):", dict(sorted(diffs.items())))

print("\n== identity ==")
kinds = Counter()
for r in rows:
    kinds.update((r.get("identity") or {}).get("kinds") or {})
print("network id kinds:", dict(kinds))
print("epic ids 32 hex:", sum((r.get("identity") or {}).get("epic_id_32_hex", 0) for r in rows), " other shape:", sum((r.get("identity") or {}).get("epic_id_other_shape", 0) for r in rows))
print("players without header stats:", sum((r.get("identity") or {}).get("players_without_header_stats", 0) for r in rows))
print("replays with duplicate names:", sum(1 for r in rows if (r.get("identity") or {}).get("duplicate_names")))
an = [r["anonymization"] for r in rows if r.get("anonymization")]
print("anonymization: replays with flag updates", sum(a["flag_updates"] > 0 for a in an), " with flag true", sum(a["flag_true"] > 0 for a in an), " with anonymized names", sum(a["anonymized_names"] > 0 for a in an), " name equal to player name", sum(a["anonymized_names_equal_to_player_name"] for a in an), " puid", sum(a["epic_puid_updates"] > 0 for a in an))

print("\n== constants (active play, net>=10) ==")
def extent(key, axis):
    vals = [r["measures"][key][axis] for r in recent if r["measures"][key][axis]]
    return (min(v[0] for v in vals), max(v[1] for v in vals)) if vals else None
for key in ("ball", "car"):
    print(key, {a: extent(key, a) for a in "xyz"})
print("speed max:", max(r["measures"]["speed_max"] for r in recent))
bins = Counter()
for r in recent:
    bins.update({int(k): v for k, v in r["measures"]["speed_bins_from_2000"].items()})
print("speed bins:", dict(sorted(bins.items())))
print("boost range:", min(r["measures"]["boost"][0] for r in recent if r["measures"]["boost"]), max(r["measures"]["boost"][1] for r in recent if r["measures"]["boost"]))
print("kickoff boost medians:", Counter(r["measures"]["kickoff_boost_median"] for r in recent).most_common(5))
print("grounded z medians:", Counter(round(r["measures"]["grounded_z_median"], 1) for r in recent if r["measures"]["grounded_z_median"]).most_common(5))
print("bad quaternions:", sum(r["measures"]["bad_quaternions"] for r in recent), " no velocity:", sum(r["measures"]["no_velocity_samples"] for r in recent), " of", sum(r["measures"]["car_samples"] for r in recent))
side = Counter()
ky = Counter()
for r in recent:
    side.update(r["measures"]["goals_side"])
    k = r["measures"]["kickoff_mean_y"]
    if k["team0"] is not None and k["team1"] is not None:
        ky[("team0<0" if k["team0"] < 0 else "team0>0", "team1>0" if k["team1"] > 0 else "team1<0")] += 1
print("kickoff sides:", {str(a): b for a, b in ky.items()})
print("goals by side:", dict(side))
print("goal ball |y| median:", st.median([r["measures"]["goal_ball_abs_y_median"] for r in recent if r["measures"]["goal_ball_abs_y_median"]]))

print("\n== inventory ==")
print("effective fps:", {k: round(f(r["measures"]["effective_fps"] for r in recent), 1) for k, f in (("min", min), ("max", max))})
aligned = [r["measures"]["phase_aligned_frames"] / max(1, r["measures"]["frames"]) for r in recent]
print("phase alignment min:", round(min(aligned), 4))
pc = Counter()
for r in recent:
    pc.update(r["measures"]["phase_counts"])
total = sum(pc.values())
print("phases:", {k: round(100 * v / total, 1) for k, v in pc.items()})
d = Counter()
runs = []
for r in recent:
    m = r["measures"]["demolitions"]
    d.update({k: m[k] for k in ("followed_by_empty", "not_empty", "unknown_victim", "unexplained_empty_runs")})
    if m["empty_run_s_median"]:
        runs.append(m["empty_run_s_median"])
print("demolitions:", dict(d), " empty run median s:", round(st.median(runs), 2) if runs else None)
p = Counter()
for r in recent:
    p.update({k: v for k, v in r["pads"].items()})
print("pads totals:", dict(p))
print("replays with fewer than 34 pads ids:", sum(r["pads"]["pads_with_id"] < 34 for r in recent), "of", len(recent))
e = Counter()
for r in recent:
    e.update(r["events"])
print("events:", dict(e))
print("goals vs header:", sum(r["events"]["goals"] == r["header"]["header_goals"] for r in recent), "of", len(recent), "match")
print("game kinds:", Counter(r["game_type"]["kind"] for r in recent), " playlists:", Counter(r["game_type"]["playlist_id"] for r in recent))

print("\n== budget ==")
full = [r for r in rows if r.get("data_ok")]
new = [r for r in full if (r["header"]["version"][2] or 0) >= 11]
for label, g in (("all", full), ("net>=11", new)):
    print(label, "n=", len(g))
    for key in ("header_ms", "network_ms", "data_ms", "phases_ms", "stats_ms", "wall_ms"):
        v = [r[key] for r in g if key in r]
        print(f"  {key}: median {st.median(v):.0f} p99 {pct(v, .99)} max {max(v)}")
    for key in ("rss_header_kb", "rss_network_kb", "rss_data_kb", "rss_phases_kb", "rss_parquet_kb", "rss_stats_kb"):
        v = [r[key] / 1024 for r in g if key in r]
        print(f"  {key[:-3]}_mb: median {st.median(v):.0f} max {max(v):.0f}")
    v = [r["parquet"]["bytes_every_frame"] / 1e6 for r in g]
    w = [r["parquet"]["bytes_every_2nd_frame"] / 1e6 for r in g]
    print(f"  parquet MB: median {st.median(v):.2f} max {max(v):.2f}; every 2nd frame median {st.median(w):.2f} max {max(w):.2f}")
    per_min = [r["parquet"]["bytes_every_frame"] / 1e6 / max(r["measures"]["duration_s"] / 60, .1) / max(r["identity"]["players"], 1) for r in g]
    print(f"  parquet MB per minute and player: median {st.median(per_min):.3f}")
    print(f"  size MB: median {st.median(r['size'] / 1e6 for r in g):.2f} max {max(r['size'] / 1e6 for r in g):.2f}")
