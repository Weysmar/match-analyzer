import { describe, expect, it } from "vitest";
import { decode } from "../../src/lib/view2d/document";
import { COLORS, drawScene, type Pen } from "../../src/lib/view2d/draw";
import { layoutFor, toScreen } from "../../src/lib/view2d/field";
import { sceneAt } from "../../src/lib/view2d/scene";
import { rawView } from "./fixture";

/** A 2D context that only remembers where cars went and what was filled. */
function recorder() {
  const translations: [number, number][] = [];
  const fills: string[] = [];
  const pen = {
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    fillRect() {
      fills.push(String(pen.fillStyle));
    },
    strokeRect() {},
    beginPath() {},
    moveTo() {},
    lineTo() {},
    stroke() {},
    arc() {},
    fill() {
      fills.push(String(pen.fillStyle));
    },
    save() {},
    restore() {},
    translate(x: number, y: number) {
      translations.push([x, y]);
    },
    rotate() {},
  };
  return { pen: pen as unknown as Pen, translations, fills };
}

const view = decode(rawView());
const layout = layoutFor(375, 2000);

describe("drawing a scene", () => {
  it("draws each shown car where it is", () => {
    const { pen, translations } = recorder();
    drawScene(pen, layout, sceneAt(view, 1), null);
    expect(translations).toHaveLength(2);
    const [x, y] = toScreen(layout, 1000, -2000);
    expect(translations[0]?.[0]).toBeCloseTo(x);
    expect(translations[0]?.[1]).toBeCloseTo(y);
  });

  it("leaves a demolished car out", () => {
    const { pen, translations } = recorder();
    drawScene(pen, layout, sceneAt(view, 2.5), null);
    expect(translations).toHaveLength(1);
  });

  it("marks the viewer's car", () => {
    const mine = recorder();
    drawScene(mine.pen, layout, sceneAt(view, 1), 41);
    const nobody = recorder();
    drawScene(nobody.pen, layout, sceneAt(view, 1), null);
    expect(mine.fills.filter((color) => color === COLORS.me)).toHaveLength(1);
    expect(nobody.fills).not.toContain(COLORS.me);
  });

  it("draws the ball over its shadow", () => {
    const { pen, fills } = recorder();
    drawScene(pen, layout, sceneAt(view, 1), null);
    expect(fills.slice(-2)).toEqual([COLORS.shadow, COLORS.ball]);
  });
});
