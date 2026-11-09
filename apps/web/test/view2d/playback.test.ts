import { describe, expect, it } from "vitest";
import { actionForKey, type Playback, reduce, START } from "../../src/lib/view2d/playback";

const DURATION = 60;
const run = (state: Playback, ...actions: Parameters<typeof reduce>[1][]) =>
  actions.reduce((current, action) => reduce(current, action, DURATION), state);

describe("playback", () => {
  it("never starts by itself", () => {
    expect(START.playing).toBe(false);
    expect(run(START, { type: "tick", elapsedS: 1 }).t).toBe(0);
  });

  it("runs at its speed while playing", () => {
    const state = run(START, { type: "toggle" }, { type: "speed", speed: 2 });
    expect(run(state, { type: "tick", elapsedS: 1.5 }).t).toBe(3);
    expect(run(state, { type: "speed", speed: 0.5 }, { type: "tick", elapsedS: 2 }).t).toBe(1);
  });

  it("stops at the end, and starts over from there", () => {
    const ended = run(START, { type: "toggle" }, { type: "tick", elapsedS: 99 });
    expect(ended).toMatchObject({ t: DURATION, playing: false });
    expect(run(ended, { type: "toggle" })).toMatchObject({ t: 0, playing: true });
  });

  it("jumps and seeks within the match", () => {
    expect(run(START, { type: "skip", byS: -5 }).t).toBe(0);
    expect(run(START, { type: "seek", t: 30 }, { type: "skip", byS: 5 }).t).toBe(35);
    expect(run(START, { type: "seek", t: 999 }).t).toBe(DURATION);
  });

  it("pauses", () => {
    expect(run(START, { type: "toggle" }, { type: "pause" }).playing).toBe(false);
    expect(run(START, { type: "toggle" }, { type: "toggle" }).playing).toBe(false);
  });
});

describe("the keyboard", () => {
  it("plays with Space and jumps 5 s with the arrows", () => {
    expect(actionForKey(" ")).toEqual({ type: "toggle" });
    expect(actionForKey("ArrowLeft")).toEqual({ type: "skip", byS: -5 });
    expect(actionForKey("ArrowRight")).toEqual({ type: "skip", byS: 5 });
    expect(actionForKey("a")).toBeNull();
  });
});
