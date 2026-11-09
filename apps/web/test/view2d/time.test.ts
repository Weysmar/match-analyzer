import { describe, expect, it } from "vitest";
import { decode } from "../../src/lib/view2d/document";
import {
  clampTime,
  clockAt,
  durationS,
  fromReplayTime,
  lerp,
  lerpAngle,
  positionAt,
  timeAtClock,
  timeOfSample,
} from "../../src/lib/view2d/time";
import { rawView } from "./fixture";

const view = decode(rawView());

describe("time and samples", () => {
  it("spans the samples at their rate", () => {
    expect(durationS(view)).toBe(4);
    expect(timeOfSample(view, 15)).toBe(1);
  });

  it("finds the sample at or before a time, and how far to the next", () => {
    expect(positionAt(view, 1)).toEqual({ index: 15, fraction: 0 });
    const between = positionAt(view, 1.05);
    expect(between.index).toBe(15);
    expect(between.fraction).toBeCloseTo(0.75);
  });

  it("stays within the match", () => {
    expect(positionAt(view, -3)).toEqual({ index: 0, fraction: 0 });
    expect(positionAt(view, 99)).toEqual({ index: 60, fraction: 0 });
    expect(clampTime(view, Number.NaN)).toBe(0);
  });

  it("interpolates a series between two samples", () => {
    expect(lerp([0, 10], { index: 0, fraction: 0.25 })).toBe(2.5);
    expect(lerp([0, 10], { index: 1, fraction: 0 })).toBe(10);
  });

  it("turns the short way round", () => {
    expect(lerpAngle([170, -170], { index: 0, fraction: 0.5 })).toBeCloseTo(180);
    expect(lerpAngle([-170, 170], { index: 0, fraction: 0.5 })).toBeCloseTo(-180);
    expect(lerpAngle([10, 30], { index: 0, fraction: 0.5 })).toBeCloseTo(20);
  });
});

describe("the game clock", () => {
  it("stands still before live play, then runs", () => {
    expect(clockAt(view, 0.5)).toBe(0);
    expect(clockAt(view, 3)).toBeCloseTo(2);
  });

  it("sends the cursor to the first time the clock reaches a value", () => {
    expect(timeAtClock(view, 0)).toBe(0);
    expect(timeAtClock(view, 2)).toBeCloseTo(3);
    // The clock is kept to the tenth: 1.1 s is first reached on sample 31.
    expect(timeAtClock(view, 1.1)).toBeCloseTo(31 / 15);
    // Between two tenths, the time between their two samples.
    expect(timeAtClock(view, 1.05)).toBeCloseTo(30.5 / 15);
    expect(timeAtClock(view, 999)).toBe(4);
  });

  it("puts a replay time on the player's time", () => {
    expect(fromReplayTime(view, 13.5)).toBe(3.5);
  });
});
