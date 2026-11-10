/**
 * The "Analysis" section of the match sheet (T16.1), worked out from the API's sheet: the
 * possession bar, kickoffs and duels in a sentence each, and the situations the detections found,
 * grouped by kind, each at its moment of play. Goal contexts have their own cards (T16.2).
 */
import type { Schemas } from "@/lib/api/client";
import type { PossessionSplit } from "@/lib/matches/metrics";
import { readClock, regulationOf } from "@/lib/matches/timeline";

export type ListedKind = "double_commit" | "overcommit" | "turnover" | "kickoff" | "fifty_fifty";
/** The order of the lists: what the player can act on first, the routine of a match last. */
export const LISTED_KINDS: readonly ListedKind[] = [
  "double_commit",
  "overcommit",
  "turnover",
  "kickoff",
  "fifty_fifty",
];

export interface BarSegment {
  part: "blue" | "loose" | "orange";
  /** Where it starts and how wide it is, from 0 to 100. */
  from: number;
  width: number;
}

/** The possession bar: blue from the left, the loose ball in the middle, orange to the right. */
export function possessionBar(split: PossessionSplit): BarSegment[] {
  const total = split.blue + split.loose + split.orange;
  if (total <= 0) return [];
  const scale = (value: number) => (100 * value) / total;
  const blue = scale(split.blue);
  const loose = scale(split.loose);
  return [
    { part: "blue" as const, from: 0, width: blue },
    { part: "loose" as const, from: blue, width: loose },
    { part: "orange" as const, from: blue + loose, width: 100 - blue - loose },
  ].filter((segment) => segment.width > 0);
}

export interface TeamCounts {
  total: number;
  blue: number;
  orange: number;
  /** Neither team: a neutral kickoff, a duel that left the ball loose. */
  none: number;
}

function countByTeam(situations: readonly Schemas["Situation"][], kind: string): TeamCounts {
  const mine = situations.filter((situation) => situation.kind === kind);
  return {
    total: mine.length,
    blue: mine.filter((situation) => situation.team === 0).length,
    orange: mine.filter((situation) => situation.team === 1).length,
    none: mine.filter((situation) => situation.team !== 0 && situation.team !== 1).length,
  };
}

/** Kickoffs by winner: the team that sent the ball into the other half. */
export function kickoffCounts(situations: readonly Schemas["Situation"][]): TeamCounts {
  return countByTeam(situations, "kickoff");
}

/** Duels by the team that had the ball afterwards. */
export function duelCounts(situations: readonly Schemas["Situation"][]): TeamCounts {
  return countByTeam(situations, "fifty_fifty");
}

export interface ListedSituation {
  id: number;
  kind: ListedKind;
  team: number | null;
  /** The players' names, in the situation's order (for a turnover: who took it, then who lost it). */
  names: string[];
  /** As the game shows it; null without the game clock. */
  clock: { overtime: boolean; clockS: number } | null;
  /** Seconds of play, for the link into the 2D view; null without the game clock. */
  playS: number | null;
  /** A double commit the opponents punished, a kickoff that led to a goal. */
  punished: boolean;
  goal: boolean;
  /** How long an overcommit lasted, in seconds. */
  durationS: number | null;
}

type MatchClock = Pick<Schemas["MatchInfo"], "game_length_s" | "overtime_from_s">;

/** The situations of each listed kind, in time order; kinds without any are left out. */
export function listSituations(
  situations: readonly Schemas["Situation"][],
  players: readonly Pick<Schemas["Player"], "match_player_id" | "name">[],
  match: MatchClock,
): { kind: ListedKind; items: ListedSituation[] }[] {
  const names = new Map(players.map((player) => [player.match_player_id, player.name]));
  const regulation = regulationOf(match.game_length_s, match.overtime_from_s);
  const onClock = match.game_length_s !== null;
  const listed = situations
    .filter((situation): situation is Schemas["Situation"] & { kind: ListedKind } =>
      (LISTED_KINDS as readonly string[]).includes(situation.kind),
    )
    .map((situation): ListedSituation => {
      const playS = onClock ? situation.game_time_s : null;
      const duration = situation.details.duration_s;
      return {
        id: situation.id,
        kind: situation.kind,
        team: situation.team,
        names: situation.players.flatMap((id) => {
          const name = names.get(id);
          return name === undefined ? [] : [name];
        }),
        clock: playS === null ? null : readClock(playS, match.overtime_from_s, regulation),
        playS,
        punished: situation.details.punished === true,
        goal: situation.details.goal === true,
        durationS: typeof duration === "number" ? duration : null,
      };
    });
  return LISTED_KINDS.map((kind) => ({
    kind,
    items: listed.filter((situation) => situation.kind === kind),
  })).filter((group) => group.items.length > 0);
}
