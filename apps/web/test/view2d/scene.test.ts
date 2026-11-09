import { describe, expect, it } from "vitest";
import { decode } from "../../src/lib/view2d/document";
import { sceneAt } from "../../src/lib/view2d/scene";
import { rawView } from "./fixture";

const view = decode(rawView());
const car = (t: number, id: number) => sceneAt(view, t).cars.find((found) => found.id === id);

describe("the scene at a given time", () => {
  it("places each car where it is then", () => {
    expect(car(1.5, 41)).toMatchObject({ x: 1500, y: -2000, yaw: 0, shown: true, team: 0 });
    expect(car(1.5, 42)).toMatchObject({ x: 0, y: 500, yaw: -90, team: 1 });
  });

  it("interpolates between samples", () => {
    expect(car(1.02, 41)?.x).toBeCloseTo(1020, 0);
    expect(car(1.02, 41)?.boost).toBeCloseTo(90, 0);
  });

  it("says when a car is demolished, and hides it", () => {
    expect(car(2.5, 42)).toMatchObject({ shown: false, demolished: true });
    expect(car(3.2, 42)).toMatchObject({ shown: true, demolished: false });
  });

  it("gives the ball's height and the clock", () => {
    const scene = sceneAt(view, 2);
    expect(scene.ball.z).toBe(293);
    expect(scene.clockS).toBeCloseTo(1);
    expect(scene.phase).toBe(3);
  });
});
