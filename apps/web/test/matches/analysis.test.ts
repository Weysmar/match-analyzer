import { describe, expect, it } from "vitest";
import type { Schemas } from "../../src/lib/api/client";
import {
  duelCounts,
  kickoffCounts,
  LISTED_KINDS,
  listSituations,
  possessionBar,
} from "../../src/lib/matches/analysis";

function situation(
  id: number,
  kind: Schemas["Situation"]["kind"],
  overrides: Partial<Schemas["Situation"]> = {},
): Schemas["Situation"] {
  return {
    id,
    kind,
    time_s: 10 * id,
    game_time_s: 10 * id,
    team: null,
    players: [],
    tags: [],
    details: {},
    ...overrides,
  };
}

const PLAYERS = [
  { match_player_id: 1, name: "Blue One" },
  { match_player_id: 2, name: "Blue Two" },
  { match_player_id: 3, name: "Orange One" },
];
// Regulation measured at 300 s: the clock reads as the game shows it.
const CLOCK = { game_length_s: 300, overtime_from_s: null };

describe("the possession bar", () => {
  it("puts blue on the left, the loose ball in the middle, orange on the right", () => {
    expect(possessionBar({ blue: 20, loose: 65, orange: 15 })).toEqual([
      { part: "blue", from: 0, width: 20 },
      { part: "loose", from: 20, width: 65 },
      { part: "orange", from: 85, width: 15 },
    ]);
  });

  it("leaves out an empty part and fills the whole width", () => {
    const bar = possessionBar({ blue: 30, loose: 0, orange: 30 });
    expect(bar.map((segment) => segment.part)).toEqual(["blue", "orange"]);
    expect(bar[1]).toEqual({ part: "orange", from: 50, width: 50 });
  });

  it("draws nothing without play", () => {
    expect(possessionBar({ blue: 0, loose: 0, orange: 0 })).toEqual([]);
  });
});

describe("kickoffs and duels", () => {
  const found = [
    situation(1, "kickoff", { team: 0 }),
    situation(2, "kickoff", { team: 1 }),
    situation(3, "kickoff", { team: 0 }),
    situation(4, "kickoff"),
    situation(5, "fifty_fifty", { team: 1 }),
    situation(6, "fifty_fifty"),
    situation(7, "turnover", { team: 0 }),
  ];

  it("count kickoffs by winner, the neutral ones apart", () => {
    expect(kickoffCounts(found)).toEqual({ total: 4, blue: 2, orange: 1, none: 1 });
  });

  it("count duels by the team with the ball afterwards", () => {
    expect(duelCounts(found)).toEqual({ total: 2, blue: 0, orange: 1, none: 1 });
  });
});

describe("the situations listed", () => {
  it("group by kind in a set order, in time order, without goal contexts", () => {
    const groups = listSituations(
      [
        situation(1, "kickoff"),
        situation(2, "turnover", { team: 1, players: [3, 1] }),
        situation(3, "double_commit", { team: 0, players: [1, 2] }),
        situation(4, "goal_context", { team: 0, players: [1, 2] }),
        situation(5, "turnover", { team: 0, players: [1, 3] }),
      ],
      PLAYERS,
      CLOCK,
    );
    expect(groups.map((group) => [group.kind, group.items.map((item) => item.id)])).toEqual([
      ["double_commit", [3]],
      ["turnover", [2, 5]],
      ["kickoff", [1]],
    ]);
    expect(LISTED_KINDS).not.toContain("goal_context");
  });

  it("name the players in the situation's order and read its details", () => {
    const [group] = listSituations(
      [
        situation(1, "double_commit", {
          team: 0,
          players: [2, 1, 99],
          details: { punished: true },
        }),
      ],
      PLAYERS,
      CLOCK,
    );
    expect(group?.items[0]).toMatchObject({
      names: ["Blue Two", "Blue One"],
      punished: true,
      goal: false,
      durationS: null,
    });
  });

  it("read an overcommit's duration and a kickoff goal", () => {
    const groups = listSituations(
      [
        situation(1, "overcommit", { team: 1, details: { duration_s: 1.65 } }),
        situation(2, "kickoff", { team: 0, details: { goal: true, kickoff_type: "diagonal" } }),
      ],
      PLAYERS,
      CLOCK,
    );
    expect(
      groups.flatMap((group) => group.items.map((item) => [item.durationS, item.goal])),
    ).toEqual([
      [1.65, false],
      [null, true],
    ]);
  });

  it("show the clock as the game does, overtime included", () => {
    const groups = listSituations(
      [
        situation(6, "turnover", { game_time_s: 60 }),
        situation(32, "turnover", { game_time_s: 320 }),
      ],
      PLAYERS,
      { game_length_s: 330, overtime_from_s: 300 },
    );
    expect(groups[0]?.items.map((item) => [item.clock, item.playS])).toEqual([
      [{ overtime: false, clockS: 240 }, 60],
      [{ overtime: true, clockS: 20 }, 320],
    ]);
  });

  it("have no clock nor link without the game clock", () => {
    const [group] = listSituations([situation(1, "turnover")], PLAYERS, {
      game_length_s: null,
      overtime_from_s: null,
    });
    expect(group?.items[0]).toMatchObject({ clock: null, playS: null });
  });

  it("are empty when nothing was found", () => {
    expect(listSituations([], PLAYERS, CLOCK)).toEqual([]);
  });
});
