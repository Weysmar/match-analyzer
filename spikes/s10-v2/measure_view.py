"""Spike of step 10, T10.4: the 2D view's document at 10, 15 and 30 Hz. For every replay of
`out/`: compressed size, and the error of linear interpolation between samples against every frame.
Also writes `out/view-sample-15hz.json` from one public replay, for the viewer prototype (T10.5).
Numbers only: players are roster rows, never names.

Usage: uv run python spikes/s10-v2/measure_view.py
"""

import gzip
import json
import math
import statistics
import sys
from pathlib import Path

import numpy as np
import polars as pl

OUT = Path(__file__).resolve().parent / "out"
RATES = (10, 15, 30)
SAMPLE_REPLAY = "post-eac-ranked-doubles-2026-04-28.replay"


def yaw(qx: np.ndarray, qy: np.ndarray, qz: np.ndarray, qw: np.ndarray) -> np.ndarray:
    return np.degrees(np.arctan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz)))


def document(frames: pl.DataFrame, rate: int) -> tuple[dict, np.ndarray]:
    """The columnar document, and the sample times it holds."""
    times = frames.group_by("frame").agg(pl.col("time_s").first()).sort("time_s")["time_s"]
    start, end = float(times.min()), float(times.max())  # type: ignore[arg-type]
    grid = np.arange(start, end, 1 / rate)
    ball = frames.group_by("frame").agg(pl.col(["time_s", "phase", "ball_x", "ball_y", "ball_z"]).first()).sort("time_s")
    t = ball["time_s"].to_numpy()

    def resample(values: np.ndarray, at: np.ndarray, base: np.ndarray) -> list[int | None]:
        ok = np.isfinite(values)
        if ok.sum() < 2:
            return [None] * len(at)
        out = np.interp(at, base[ok], values[ok])
        return [int(round(v)) for v in out]

    doc: dict = {
        "version": 1,
        "rate": rate,
        "start_s": start,
        "t": [int(round((g - start) * 1000)) for g in grid],
        "phase": [int(p) for p in np.interp(grid, t, ball["phase"].to_numpy().astype(float)).round()],
        "ball": {k: resample(ball[f"ball_{k}"].to_numpy().astype(float), grid, t) for k in "xyz"},
        "players": {},
    }
    for (idx,), group in frames.sort("time_s").partition_by("player_idx", as_dict=True).items():
        gt = group["time_s"].to_numpy()
        present = group["present"].to_numpy() & ~group["demolished"].to_numpy()
        heading = yaw(*(group[c].to_numpy().astype(float) for c in ("qx", "qy", "qz", "qw")))
        doc["players"][str(idx)] = {
            "team": int(group["team"][0]),
            **{k: resample(np.where(present, group[k].to_numpy().astype(float), np.nan), grid, gt) for k in "xyz"},
            "yaw": resample(heading, grid, gt),
            "boost": resample(group["boost"].to_numpy().astype(float), grid, gt),
            "on": [int(v) for v in np.interp(grid, gt, present.astype(float)).round()],
        }
    return doc, grid


def interpolation_error(frames: pl.DataFrame, doc: dict, grid: np.ndarray) -> list[float]:
    """Distance between each real position and the one interpolated from the samples, in uu."""
    errors: list[float] = []
    ball = frames.group_by("frame").agg(pl.col(["time_s", "ball_x", "ball_y", "ball_z"]).first())
    bt = ball["time_s"].to_numpy()
    for prefix, rows, times in (("ball", ball, bt),):
        real = rows.select(f"{prefix}_x", f"{prefix}_y", f"{prefix}_z").to_numpy().astype(float)
        est = np.stack([np.interp(times, grid, np.array([v if v is not None else np.nan for v in doc["ball"][k]], float)) for k in "xyz"], axis=1)
        d = np.linalg.norm(real - est, axis=1)
        errors += [float(x) for x in d[np.isfinite(d)]]
    for (idx,), group in frames.partition_by("player_idx", as_dict=True).items():
        g = group.filter(pl.col("present") & ~pl.col("demolished"))
        if g.height == 0:
            continue
        p = doc["players"][str(idx)]
        real = g.select("x", "y", "z").to_numpy().astype(float)
        est = np.stack([np.interp(g["time_s"].to_numpy(), grid, np.array([v if v is not None else np.nan for v in p[k]], float)) for k in "xyz"], axis=1)
        d = np.linalg.norm(real - est, axis=1)
        errors += [float(x) for x in d[np.isfinite(d)]]
    return errors


def main() -> int:
    sizes: dict[int, list[int]] = {rate: [] for rate in RATES}
    p95: dict[int, list[float]] = {rate: [] for rate in RATES}
    p99: dict[int, list[float]] = {rate: [] for rate in RATES}
    folders = [p for p in sorted(OUT.iterdir()) if (p / "frames.parquet").exists()]
    for folder in folders:
        frames = pl.read_parquet(folder / "frames.parquet")
        if frames.height == 0:
            continue
        for rate in RATES:
            doc, grid = document(frames, rate)
            sizes[rate].append(len(gzip.compress(json.dumps(doc, separators=(",", ":")).encode())))
            errors = interpolation_error(frames, doc, grid)
            if errors:
                q = np.percentile(errors, [95, 99])
                p95[rate].append(float(q[0]))
                p99[rate].append(float(q[1]))
    print(f"replays: {len(folders)}")
    for rate in RATES:
        s = sizes[rate]
        print(
            f"{rate:2} Hz: gzip median {statistics.median(s) / 1024:.0f} KB, max {max(s) / 1024:.0f} KB; "
            f"interpolation error p95 median {statistics.median(p95[rate]):.0f} uu "
            f"(worst replay {max(p95[rate]):.0f}), p99 median {statistics.median(p99[rate]):.0f} uu"
        )

    sample = Path(__file__).resolve().parents[2] / "tests/fixtures/replays/public" / SAMPLE_REPLAY
    import hashlib
    digest = hashlib.sha256(sample.read_bytes()).hexdigest()[:12] if sample.exists() else ""
    if digest and (OUT / digest / "frames.parquet").exists():
        doc, _ = document(pl.read_parquet(OUT / digest / "frames.parquet"), 15)
        events = json.loads((OUT / digest / "events.json").read_text())
        doc["goals"] = [
            {"t": int(round((g["time_s"] - doc["start_s"]) * 1000)), "team": g["team"]}
            for g in events["goals"]
        ]
        text = json.dumps(doc, separators=(",", ":"))
        (OUT / "view-sample-15hz.json").write_text(text)
        (OUT / "view.js").write_text(f"window.VIEW = {text};\n")
        print(f"sample written from the public replay ({math.ceil(len(json.dumps(doc)) / 1024)} KB raw)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
