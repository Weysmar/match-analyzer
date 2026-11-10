import { describe, expect, it } from "vitest";
import type { Schemas } from "../../src/lib/api/client";
import { GOAL_TAGS, goalCards } from "../../src/lib/matches/conceded";

const PLAYERS = [
  { match_player_id: 1, name: "Blue One", team: 0, is_me: true },
  { match_player_id: 2, name: "Blue Two", team: 0, is_me: false },
  { match_player_id: 3, name: "Orange One", team: 1, is_me: false },
] as Schemas["Player"][];

const MATCH = {
  game_length_s: 300,
  overtime_from_s: null,
  duration_s: 360,
} as Schemas["MatchInfo"];

const GOALS: Schemas["Goal"][] = [
  { time_s: 50.5, game_time_s: 40.0, team: 1, player_name: "Orange One" },
  { time_s: 120.25, game_time_s: 100.04, team: 0, player_name: "Blue Two" },
];

function context(overrides: Partial<Schemas["Situation"]> = {}): Schemas["Situation"] {
  return {
    id: 7,
    kind: "goal_context",
    time_s: 50.5,
    game_time_s: 40,
    team: 0,
    players: [1, 2],
    tags: [],
    details: {},
    ...overrides,
  };
}

function cards(situations: Schemas["Situation"][]) {
  return goalCards({ situations, goals: GOALS, players: PLAYERS, match: MATCH });
}

describe("the cards of the goals conceded", () => {
  it("find their goal: the scorer, the score then, the clock", () => {
    const [card] = cards([context({ details: { window_s: 10 } })]);
    expect(card).toMatchObject({
      id: 7,
      team: 0,
      scorerName: "Orange One",
      score: { blue: 0, orange: 1 },
      clock: { overtime: false, clockS: 260 },
      playS: 40,
      windowStartS: 30,
    });
  });

  it("match a goal whose time was rounded", () => {
    const [card] = cards([context({ time_s: 120.2, game_time_s: 100, team: 1 })]);
    expect(card?.score).toEqual({ blue: 1, orange: 1 });
    expect(card?.scorerName).toBe("Blue Two");
  });

  it("show the tags in their set order, and only known ones", () => {
    const [card] = cards([context({ tags: ["own_touch_last", "made_up", "double_commit"] })]);
    expect(card?.tags).toEqual(["double_commit", "own_touch_last"]);
    expect(GOAL_TAGS).toHaveLength(9);
  });

  it("name the last toucher, who lost the ball and the roles then", () => {
    const [card] = cards([
      context({
        details: {
          last_touch: { player: 2, team: 0 },
          lost_ball: {
            player: 1,
            before_goal_s: 5.6,
            ball_y: -1200,
            clock_s: 34.4,
            roles: [
              { player: 2, role: "first" },
              { player: 1, role: "second" },
              { player: 9, role: "first" },
              { player: 1, role: "captain" },
            ],
          },
        },
      }),
    ]);
    expect(card?.lastTouch).toEqual({ name: "Blue Two", team: 0 });
    expect(card?.lostBall).toEqual({
      name: "Blue One",
      beforeGoalS: 5.6,
      ownHalf: true,
      roles: [
        { name: "Blue Two", role: "first" },
        { name: "Blue One", role: "second" },
      ],
    });
  });

  it("read each defender at the shot, in meters", () => {
    const [card] = cards([
      context({
        details: {
          defenders: [
            { player: 1, goal_distance: 3500, boost: 19, demolished: false, last_back: true },
            { player: 2, goal_distance: null, boost: null, demolished: true, last_back: false },
            { player: 42, goal_distance: 100, boost: 50, demolished: false, last_back: false },
          ],
        },
      }),
    ]);
    expect(card?.defenders).toEqual([
      { name: "Blue One", distanceM: 35, boost: 19, demolished: false, lastBack: true },
      { name: "Blue Two", distanceM: null, boost: null, demolished: true, lastBack: false },
    ]);
  });

  it("leave out facts that are missing or malformed", () => {
    const [card] = cards([
      context({
        details: { last_touch: null, lost_ball: "nope", defenders: { player: 1 }, window_s: "10" },
      }),
    ]);
    expect(card).toMatchObject({
      lastTouch: null,
      lostBall: null,
      defenders: [],
      windowStartS: null,
    });
  });

  it("have no clock without the game clock, and no score for an unknown goal", () => {
    const [card] = goalCards({
      situations: [context({ time_s: 999 })],
      goals: GOALS,
      players: PLAYERS,
      match: { ...MATCH, game_length_s: null },
    });
    expect(card).toMatchObject({ clock: null, playS: null, score: null, scorerName: null });
  });

  it("are only for goal contexts", () => {
    expect(cards([context({ kind: "turnover" })])).toEqual([]);
  });
});
