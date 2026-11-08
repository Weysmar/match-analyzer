import { describe, expect, it } from "vitest";
import type { Schemas } from "../../src/lib/api/client";
import {
  byTeam,
  claimable,
  duration,
  inProgress,
  playlistKind,
  teamSize,
} from "../../src/lib/matches/describe";

const player = (
  id: number,
  team: number,
  score: number | null,
  isBot = false,
): Schemas["Player"] => ({
  match_player_id: id,
  name: `P${id}`,
  team,
  score,
  goals: null,
  assists: null,
  saves: null,
  shots: null,
  is_bot: isBot,
  is_me: false,
});

describe("a match", () => {
  it.each([
    ["pending", true],
    ["parsing", true],
    ["parsed", true],
    ["analyzing", true],
    ["ready", false],
    ["header_only", false],
    ["failed", false],
  ] as const)("in status %s is in progress: %s", (status, expected) => {
    expect(inProgress(status)).toBe(expected);
  });

  it.each([
    ["11", "ranked"],
    ["1", "casual"],
    ["6", "private"],
    ["27", "other"],
    [null, "other"],
  ] as const)("playlist %s reads as %s", (playlist, kind) => {
    expect(playlistKind(playlist)).toBe(kind);
  });

  it("names its format", () => {
    expect(teamSize(2)).toBe("2v2");
    expect(teamSize(null)).toBeNull();
  });

  it("reads its duration", () => {
    expect(duration(305.6)).toBe("5:06");
    expect(duration(null)).toBeNull();
  });
});

describe("players", () => {
  it("go blue then orange, each by score", () => {
    const [blue, orange] = byTeam([
      player(1, 1, 100),
      player(2, 0, 50),
      player(3, 0, 300),
      player(4, 1, null),
    ]);
    expect(blue.map((p) => p.match_player_id)).toEqual([3, 2]);
    expect(orange.map((p) => p.match_player_id)).toEqual([1, 4]);
  });

  it("can be claimed, bots excepted", () => {
    expect(
      claimable([player(1, 0, 0), player(2, 1, 0, true)]).map((p) => p.match_player_id),
    ).toEqual([1]);
  });
});
