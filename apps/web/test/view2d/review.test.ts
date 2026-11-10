import { describe, expect, it } from "vitest";
import type { Match2d, Situation } from "../../src/lib/view2d/document";
import {
  anyFileName,
  type GoalItem,
  goalLabelFile,
  goalQueue,
  parseAnyLabelFile,
  RANDOM_WINDOWS,
  recallWindows,
  WINDOW_S,
  windowLabelFile,
} from "../../src/lib/view2d/review";

const MATCH = "731bfcac-3c1f-5aa8-9259-226a1098ea5c";
const NOW = new Date("2026-11-10T20:00:00Z");

/** 300 s of play at one sample a second, the clock running from the start. */
function view(goalsAt: number[], situations: Situation[]): Match2d {
  const samples = 301;
  const zeros = Array.from({ length: samples }, () => 0);
  return {
    rateHz: 1,
    startS: 0,
    samples,
    clockS: Array.from({ length: samples }, (_, index) => index),
    phase: zeros.map(() => 3),
    ball: { x: zeros, y: zeros, z: zeros },
    cars: [],
    goals: goalsAt.map((t) => ({ t, team: 0, player: null })),
    demolitions: [],
    touches: [],
    situations,
  };
}

const at = (kind: Situation["kind"], t: number): Situation => ({
  kind,
  t,
  team: 0,
  players: [],
});

describe("the windows of play", () => {
  const found = view(
    [100, 200],
    [at("turnover", 95), at("double_commit", 150), at("overcommit", 205)],
  );
  const windows = recallWindows(found, MATCH);

  it("cover the 10 s before each goal, then a few drawn at random, none overlapping", () => {
    const before = windows.filter((window) => window.source === "before_goal");
    expect(before.map((window) => [window.startClockS, window.endClockS]).sort()).toEqual([
      [190, 200],
      [90, 100],
    ]);
    expect(windows.filter((window) => window.source === "random")).toHaveLength(RANDOM_WINDOWS);
    const sorted = [...windows].sort((a, b) => a.startClockS - b.startClockS);
    for (const [index, window] of sorted.entries()) {
      expect(window.endClockS - window.startClockS).toBeCloseTo(WINDOW_S);
      const next = sorted[index + 1];
      if (next) expect(next.startClockS).toBeGreaterThanOrEqual(window.endClockS);
    }
  });

  it("know which detector found something in them", () => {
    const beforeFirst = windows.find((window) => window.startClockS === 90);
    expect(beforeFirst?.detected).toEqual({
      turnover: true,
      double_commit: false,
      overcommit: false,
    });
    const beforeSecond = windows.find((window) => window.startClockS === 190);
    expect(beforeSecond?.detected).toEqual({
      turnover: false,
      double_commit: false,
      overcommit: false,
    });
  });

  it("are the same on every visit", () => {
    expect(recallWindows(found, MATCH)).toEqual(windows);
  });

  it("need at least one window's length of play", () => {
    const short = { ...view([], []), samples: 6, clockS: [0, 1, 2, 3, 4, 5] };
    expect(recallWindows(short, MATCH)).toEqual([]);
  });

  it("go to a file with only what was judged", () => {
    const file = windowLabelFile(
      MATCH,
      windows,
      new Map([
        [0, { turnover: "true" as const }],
        [1, {}],
      ]),
      NOW,
    );
    expect(file.windows).toHaveLength(1);
    expect(file.windows[0]?.verdicts).toEqual({ turnover: "true" });
    expect(parseAnyLabelFile(JSON.parse(JSON.stringify(file)))).not.toBeNull();
    expect(anyFileName(file)).toBe(`${MATCH}-windows.json`);
  });
});

describe("the review of the goals conceded", () => {
  const goals: GoalItem[] = [10, 20, 30, 40, 50].map((clockS, index) => ({
    timeS: clockS + 7,
    clockS,
    windowS: 10,
    detected: index === 0 ? ["own_touch_last", "double_commit"] : [],
  }));

  it("is shuffled, the same way on every visit", () => {
    const order = goalQueue(goals, MATCH).map((goal) => goal.clockS);
    expect([...order].sort((a, b) => a - b)).toEqual([10, 20, 30, 40, 50]);
    expect(goalQueue(goals, MATCH).map((goal) => goal.clockS)).toEqual(order);
  });

  it("keeps the detected tags in the file, in the cards' order, and only judged goals", () => {
    const file = goalLabelFile(
      MATCH,
      goals,
      new Map([[0, { double_commit: "true" as const, kickoff_goal: "false" as const }]]),
      NOW,
    );
    expect(file.goals).toEqual([
      {
        time_s: 17,
        clock_s: 10,
        detected: ["double_commit", "own_touch_last"],
        verdicts: { double_commit: "true", kickoff_goal: "false" },
      },
    ]);
    expect(parseAnyLabelFile(JSON.parse(JSON.stringify(file)))).not.toBeNull();
    expect(anyFileName(file)).toBe(`${MATCH}-goals.json`);
  });
});

describe("the export of any label file", () => {
  const goals = {
    version: 1,
    match_id: MATCH,
    kind: "goals",
    labeled_at: NOW.toISOString(),
    goals: [{ time_s: 1, clock_s: 1, detected: [], verdicts: { overcommit: "true" } }],
  };

  it("refuses an unknown tag, an extra field or a bad match id", () => {
    const bad = (change: (copy: Record<string, unknown>) => void) => {
      const copy = JSON.parse(JSON.stringify(goals)) as Record<string, unknown>;
      change(copy);
      return parseAnyLabelFile(copy);
    };
    expect(parseAnyLabelFile(goals)).not.toBeNull();
    expect(
      bad((copy) => {
        (copy.goals as Record<string, unknown>[])[0] = {
          time_s: 1,
          clock_s: 1,
          detected: ["made_up"],
          verdicts: {},
        };
      }),
    ).toBeNull();
    expect(bad((copy) => Object.assign(copy, { extra: true }))).toBeNull();
    expect(bad((copy) => Object.assign(copy, { match_id: "../etc" }))).toBeNull();
    expect(bad((copy) => Object.assign(copy, { kind: "other" }))).toBeNull();
  });

  it("still takes the verdicts on detections", () => {
    const detections = {
      version: 1,
      match_id: MATCH,
      detector: "turnover",
      labeled_at: NOW.toISOString(),
      labels: [{ time_s: 1, clock_s: 1, verdict: "true" }],
    };
    const file = parseAnyLabelFile(detections);
    expect(file).not.toBeNull();
    expect(file && anyFileName(file)).toBe(`${MATCH}-turnover.json`);
  });
});
