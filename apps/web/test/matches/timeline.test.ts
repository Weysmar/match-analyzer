import { describe, expect, it } from "vitest";
import type { Schemas } from "../../src/lib/api/client";
import { formatClock, placeGoals, REGULATION_S } from "../../src/lib/matches/timeline";

type Goal = Schemas["Goal"];

const goal = (team: number, gameTimeS: number | null, timeS = 0): Goal => ({
  team,
  game_time_s: gameTimeS,
  time_s: timeS,
  player_name: `P${team}`,
});

const clockOf = (length: number, overtimeFrom: number | null = null) => ({
  duration_s: 999,
  game_length_s: length,
  overtime_from_s: overtimeFrom,
});

describe("goals on the game clock", () => {
  it("sit in proportion of the match", () => {
    const { goals, onClock, overtimeLeft } = placeGoals(
      [goal(0, 75), goal(1, 150)],
      clockOf(REGULATION_S),
    );
    expect(onClock).toBe(true);
    expect(overtimeLeft).toBeNull();
    expect(goals.map((placed) => placed.left)).toEqual([25, 50]);
    expect(goals.map((placed) => placed.clockS)).toEqual([225, 150]);
  });

  it("read the time left as the game shows it, the measured clock scaled back to 300 s", () => {
    // A five-minute match measures 306 s of play (A63): its last second reads 0:00.
    const { goals } = placeGoals([goal(0, 153), goal(1, 306)], clockOf(306));
    expect(goals[0]?.clockS).toBeCloseTo(150);
    expect(goals[1]?.clockS).toBeCloseTo(0);
  });

  it("place an overtime after regulation, and its golden goal at the end", () => {
    const { goals, overtimeLeft } = placeGoals(
      [goal(0, 100), goal(1, 200), goal(1, 360)],
      clockOf(360, 300),
    );
    expect(overtimeLeft).toBeCloseTo((100 * 300) / 360);
    const golden = goals[2];
    expect(golden?.overtime).toBe(true);
    expect(golden?.left).toBe(100);
    expect(golden?.clockS).toBeCloseTo(60);
    expect(goals[0]?.overtime).toBe(false);
    expect(goals[0]?.clockS).toBeCloseTo(200);
  });

  it("keep a short match on a five-minute axis", () => {
    // A forfeit: 120 s of play, the axis still covers regulation.
    const { goals } = placeGoals([goal(0, 60)], clockOf(120));
    expect(goals[0]?.left).toBe(20);
    expect(goals[0]?.clockS).toBe(240);
  });

  it("never leave the timeline", () => {
    const { goals } = placeGoals([goal(0, 0), goal(1, 310)], clockOf(305));
    expect(goals.map((placed) => placed.left)).toEqual([0, 100]);
    expect(goals[1]?.clockS).toBe(0);
  });

  it("carry the running score", () => {
    const { goals } = placeGoals([goal(0, 10), goal(0, 20), goal(1, 30)], clockOf(REGULATION_S));
    expect(goals.map((placed) => [placed.blue, placed.orange])).toEqual([
      [1, 0],
      [2, 0],
      [2, 1],
    ]);
  });
});

describe("goals without the game clock", () => {
  it("fall back on the replay's time, without a time shown", () => {
    const { goals, onClock, overtimeLeft } = placeGoals([goal(0, null, 100), goal(1, null, 300)], {
      duration_s: 400,
      game_length_s: null,
      overtime_from_s: null,
    });
    expect(onClock).toBe(false);
    expect(overtimeLeft).toBeNull();
    expect(goals.map((placed) => placed.left)).toEqual([25, 75]);
    expect(goals.every((placed) => placed.clockS === null)).toBe(true);
  });

  it("use the last goal when the duration is unknown or short", () => {
    const { goals } = placeGoals([goal(0, null, 50), goal(1, null, 200)], {
      duration_s: null,
      game_length_s: null,
      overtime_from_s: null,
    });
    expect(goals.map((placed) => placed.left)).toEqual([25, 100]);
  });

  it("ignore an overtime when a goal lacks its clock", () => {
    const { onClock, overtimeLeft } = placeGoals([goal(0, null, 50)], clockOf(360, 300));
    expect(onClock).toBe(false);
    expect(overtimeLeft).toBeNull();
  });
});

describe("a clock", () => {
  it.each([
    [0, "0:00"],
    [59.4, "0:59"],
    [59.6, "1:00"],
    [225, "3:45"],
    [600, "10:00"],
  ])("%s s reads %s", (seconds, text) => {
    expect(formatClock(seconds)).toBe(text);
  });
});
