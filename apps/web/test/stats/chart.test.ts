import { describe, expect, it } from "vitest";
import type { Schemas } from "../../src/lib/api/client";
import { domain, geometry, PADDING } from "../../src/lib/stats/chart";

const point = (value: number | null, index = 0, verified = true): Schemas["HistoryPoint"] => ({
  match_id: `m${index}`,
  played_at: null,
  value,
  verified,
});

const WIDTH = 400;
const HEIGHT = 200;

describe("the history chart", () => {
  it("with no point, draws nothing", () => {
    expect(geometry([], WIDTH, HEIGHT)).toEqual({ points: [], path: null, ticks: [] });
  });

  it("with matches but no value, draws nothing either", () => {
    expect(geometry([point(null), point(null, 1)], WIDTH, HEIGHT).points).toEqual([]);
  });

  it("with one point, puts it in the middle, without a line", () => {
    const shape = geometry([point(42)], WIDTH, HEIGHT);
    expect(shape.points).toHaveLength(1);
    const [only] = shape.points;
    expect(only?.x).toBeCloseTo(PADDING.left + (WIDTH - PADDING.left - PADDING.right) / 2);
    expect(only?.y).toBeCloseTo(PADDING.top + (HEIGHT - PADDING.top - PADDING.bottom) / 2);
    expect(shape.path).toBeNull();
    expect(shape.ticks.map((tick) => tick.value)[1]).toBeCloseTo(42);
  });

  it("with 20 points, spreads them evenly from edge to edge, oldest left", () => {
    const values = Array.from({ length: 20 }, (_, index) => index * 5);
    const shape = geometry(
      values.map((value, index) => point(value, index)),
      WIDTH,
      HEIGHT,
    );
    expect(shape.points).toHaveLength(20);
    expect(shape.points[0]?.x).toBeCloseTo(PADDING.left);
    expect(shape.points[19]?.x).toBeCloseTo(WIDTH - PADDING.right);
    const steps = shape.points.slice(1).map((p, i) => p.x - (shape.points[i]?.x ?? 0));
    for (const step of steps) expect(step).toBeCloseTo(steps[0] ?? 0);
    // Higher values sit higher: smaller y.
    expect(shape.points[19]?.y).toBeLessThan(shape.points[0]?.y ?? 0);
    expect(shape.path?.match(/M/g)).toHaveLength(1);
    for (const p of shape.points) {
      expect(p.y).toBeGreaterThanOrEqual(PADDING.top);
      expect(p.y).toBeLessThanOrEqual(HEIGHT - PADDING.bottom);
    }
  });

  it("leaves a gap where a match has no value", () => {
    const shape = geometry(
      [point(1, 0), point(2, 1), point(null, 2), point(3, 3), point(4, 4)],
      WIDTH,
      HEIGHT,
    );
    expect(shape.points).toHaveLength(4);
    expect(shape.path?.match(/M/g)).toHaveLength(2);
  });

  it("keeps whether each match is verified", () => {
    const shape = geometry([point(1, 0, false), point(2, 1, true)], WIDTH, HEIGHT);
    expect(shape.points.map((p) => p.verified)).toEqual([false, true]);
  });

  it("puts three gridlines across the values", () => {
    const shape = geometry([point(10, 0), point(30, 1)], WIDTH, HEIGHT);
    const [low, middle, high] = shape.ticks.map((tick) => tick.value);
    expect(low).toBeLessThan(10);
    expect(middle).toBeCloseTo(20);
    expect(high).toBeGreaterThan(30);
  });
});

describe("the range drawn", () => {
  it("leaves room around the values", () => {
    expect(domain([10, 30])).toEqual([8, 32]);
  });

  it("is never empty", () => {
    expect(domain([50])).toEqual([45, 55]);
    expect(domain([0, 0])).toEqual([-1, 1]);
  });
});
