import { describe, expect, it } from "vitest";
import { placeGoals } from "../../src/lib/matches/timeline";
import {
  goalLink,
  LEAD_S,
  parseT,
  SITUATION_LEAD_S,
  situationLink,
  viewLink,
} from "../../src/lib/view2d/links";

describe("links into the view", () => {
  it("point at seconds of play, to the tenth, on the player's anchor", () => {
    expect(viewLink(61.27)).toBe("?t=61.3#view");
    expect(viewLink(-2)).toBe("?t=0#view");
  });

  it(`open a goal ${LEAD_S} s before it, never before the start`, () => {
    expect(goalLink(100)).toBe("?t=95#view");
    expect(goalLink(3)).toBe("?t=0#view");
  });

  it(`open a situation ${SITUATION_LEAD_S} s before it, never before the start`, () => {
    expect(situationLink(61.27)).toBe("?t=59.3#view");
    expect(situationLink(1)).toBe("?t=0#view");
  });

  it("read the time of the address, and nothing else", () => {
    expect(parseT("95")).toBe(95);
    expect(parseT("12.5")).toBe(12.5);
    for (const value of [null, undefined, "", " ", "abc", "-3", "Infinity"]) {
      expect(parseT(value)).toBeNull();
    }
  });
});

describe("a goal's seconds of play", () => {
  const goal = (time_s: number, game_time_s: number | null) => ({
    time_s,
    game_time_s,
    team: 0,
    player_name: null,
  });

  it("come with the game clock, as the view counts them", () => {
    const { goals } = placeGoals([goal(80, 61.2)], {
      duration_s: 400,
      game_length_s: 305,
      overtime_from_s: null,
    });
    expect(goals[0]?.playS).toBe(61.2);
  });

  it("are unknown without it: no link then", () => {
    const { goals } = placeGoals([goal(80, null)], {
      duration_s: 400,
      game_length_s: null,
      overtime_from_s: null,
    });
    expect(goals[0]?.playS).toBeNull();
  });
});
