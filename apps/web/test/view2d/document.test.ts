import { describe, expect, it } from "vitest";
import { decode, loadView, undelta, ViewFormatError } from "../../src/lib/view2d/document";
import { rawView } from "./fixture";

describe("decoding the document", () => {
  it("turns differences back into positions", () => {
    expect(undelta([5, 2, 0, -10, 3])).toEqual([5, 7, 7, -3, 0]);
    const view = decode(rawView());
    const blue = view.cars.find((car) => car.id === 41);
    expect(blue?.x[15]).toBe(1000);
    expect(blue?.yaw[15]).toBe(0);
    expect(view.ball.z[30]).toBe(293);
  });

  it("reads the clock in seconds and events on the player's time", () => {
    const view = decode(rawView());
    expect(view.clockS[30]).toBe(1);
    expect(view.goals).toEqual([{ t: 3.5, team: 0, player: 41 }]);
    expect(view.demolitions).toEqual([{ t: 2, attacker: 41, victim: 42 }]);
    expect(view.touches).toEqual([{ t: 1.5, player: 41 }]);
  });

  it("keeps touches unknown when they were not detected", () => {
    expect(decode({ ...rawView(), touches: null }).touches).toBeNull();
  });

  it.each([
    ["another version", { version: 2 }],
    ["a series of the wrong length", { phase: [1, 2] }],
    ["no grid", { samples: 0 }],
    ["a value that is no number", { clock_ds: Array(61).fill("1") }],
  ])("refuses %s", (_, change) => {
    expect(() => decode({ ...rawView(), ...change })).toThrow(ViewFormatError);
  });
});

describe("loading the document", () => {
  async function gzipped(text: string): Promise<Response> {
    const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
    return new Response(stream);
  }

  it("unpacks what the store sends", async () => {
    const body = await gzipped(JSON.stringify(rawView()));
    const view = await loadView("https://store.test/views/x.json.gz", async () => body);
    expect(view.samples).toBe(61);
  });

  it("says so when the store refuses", async () => {
    const refused = async () => new Response("expired", { status: 403 });
    await expect(loadView("https://store.test/x", refused)).rejects.toThrow(ViewFormatError);
  });
});
