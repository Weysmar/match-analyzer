import { describe, expect, it } from "vitest";
import { FIELD, layoutFor, screenAngle, toScreen } from "../../src/lib/view2d/field";

const LONG = 2 * (FIELD.halfLength + FIELD.goalDepth);
const SHORT = 2 * FIELD.halfWidth;

describe("the field on screen", () => {
  it("stands upright on a phone and keeps its proportions", () => {
    const layout = layoutFor(375, 2000);
    expect(layout.orientation).toBe("upright");
    expect(layout.width).toBeCloseTo(375);
    expect(layout.height / layout.width).toBeCloseTo(LONG / SHORT);
  });

  it("lies on its side on a computer, within the height it is given", () => {
    const layout = layoutFor(1000, 400);
    expect(layout.orientation).toBe("sideways");
    expect(layout.height).toBeCloseTo(400);
    expect(layout.width / layout.height).toBeCloseTo(LONG / SHORT);
  });

  it("puts blue's goal at the bottom upright, on the left sideways", () => {
    const upright = layoutFor(375, 2000);
    const [, blueY] = toScreen(upright, 0, -FIELD.halfLength);
    const [, orangeY] = toScreen(upright, 0, FIELD.halfLength);
    expect(blueY).toBeGreaterThan(orangeY);
    const sideways = layoutFor(1000, 400);
    const [blueX] = toScreen(sideways, 0, -FIELD.halfLength);
    const [orangeX] = toScreen(sideways, 0, FIELD.halfLength);
    expect(blueX).toBeLessThan(orangeX);
  });

  it("maps the field's center to the canvas's center", () => {
    const layout = layoutFor(375, 2000);
    const [x, y] = toScreen(layout, 0, 0);
    expect(x).toBeCloseTo(layout.width / 2);
    expect(y).toBeCloseTo(layout.height / 2);
  });

  it("turns headings with the field, without mirroring them", () => {
    const upright = layoutFor(375, 2000);
    // Facing +y is facing up the screen; facing +x, right.
    expect(screenAngle(upright, 90)).toBeCloseTo(-Math.PI / 2);
    expect(screenAngle(upright, 0)).toBeCloseTo(0);
    const sideways = layoutFor(1000, 400);
    // A quarter turn clockwise: +y points right, +x down.
    expect(screenAngle(sideways, 90)).toBeCloseTo(0);
    expect(screenAngle(sideways, 0)).toBeCloseTo(Math.PI / 2);
  });
});
