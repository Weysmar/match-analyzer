/**
 * The cards of the goals conceded (T16.2), from the `goal_context` situations of the match sheet:
 * which usual causes were there (the tags), and the facts of the play before the goal, shown
 * without judgment. `details` comes from the API as loose JSON: each fact is read with a check,
 * and a fact that is not what it should be is left out rather than shown wrong.
 */
import type { Schemas } from "@/lib/api/client";
import { placeGoals, readClock, regulationOf } from "@/lib/matches/timeline";

/** The tags in the order a card shows them: the team's play first, then its last defender. */
export const GOAL_TAGS = [
  "double_commit",
  "overcommit",
  "turnover_own_half",
  "beaten_to_ball",
  "last_back_far",
  "last_back_low_boost",
  "defender_demolished",
  "kickoff_goal",
  "own_touch_last",
] as const;
export type GoalTag = (typeof GOAL_TAGS)[number];

export type Role = "first" | "second" | "third" | "ambiguous";
const ROLES: readonly Role[] = ["first", "second", "third", "ambiguous"];

export interface Defender {
  name: string;
  /** Meters from their own goal at the shot; null when away or demolished. */
  distanceM: number | null;
  boost: number | null;
  demolished: boolean;
  lastBack: boolean;
}

export interface LostBall {
  /** Who lost it, if known. */
  name: string | null;
  /** Seconds of play from the lost ball to the goal. */
  beforeGoalS: number | null;
  /** Whether the ball was in the conceding team's half then; null when unknown. */
  ownHalf: boolean | null;
  roles: { name: string; role: Role }[];
}

export interface GoalCard {
  id: number;
  /** The team that conceded it. */
  team: number | null;
  scorerName: string | null;
  /** The score once this goal counts; null when the goal is not found among the match's goals. */
  score: { blue: number; orange: number } | null;
  clock: { overtime: boolean; clockS: number } | null;
  /** Seconds of play at the goal, and at the start of its window, for the 2D view. */
  playS: number | null;
  windowStartS: number | null;
  tags: GoalTag[];
  lastTouch: { name: string; team: number | null } | null;
  lostBall: LostBall | null;
  defenders: Defender[];
}

const METERS_PER_UU = 0.01;
// The API's goal times and the situation's come from the same file: equal, give or take rounding.
const SAME_GOAL_S = 0.05;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const asNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

type Sheet = Pick<Schemas["MatchSheet"], "situations" | "goals" | "players" | "match">;

/** One card per goal conceded, in time order; none before the analysis. */
export function goalCards(sheet: Sheet): GoalCard[] {
  const names = new Map(sheet.players.map((player) => [player.match_player_id, player.name]));
  const nameOf = (value: unknown): string | null => {
    const id = asNumber(value);
    return id === null ? null : (names.get(id) ?? null);
  };
  const timeline = placeGoals(sheet.goals, sheet.match);
  const regulation = regulationOf(sheet.match.game_length_s, sheet.match.overtime_from_s);
  const onClock = sheet.match.game_length_s !== null;

  return sheet.situations
    .filter((situation) => situation.kind === "goal_context")
    .map((situation): GoalCard => {
      const index = sheet.goals.findIndex(
        (goal) => Math.abs(goal.time_s - situation.time_s) <= SAME_GOAL_S,
      );
      const placed = index >= 0 ? timeline.goals[index] : undefined;
      const details = situation.details;
      const playS = onClock ? situation.game_time_s : null;
      const windowS = asNumber(details.window_s);
      return {
        id: situation.id,
        team: situation.team,
        scorerName: placed?.playerName ?? null,
        score: placed ? { blue: placed.blue, orange: placed.orange } : null,
        clock: playS === null ? null : readClock(playS, sheet.match.overtime_from_s, regulation),
        playS,
        windowStartS: playS !== null && windowS !== null ? Math.max(0, playS - windowS) : null,
        tags: GOAL_TAGS.filter((tag) => situation.tags.includes(tag)),
        lastTouch: lastTouch(details.last_touch, nameOf),
        lostBall: lostBall(details.lost_ball, nameOf),
        defenders: defenders(details.defenders, nameOf),
      };
    });
}

function lastTouch(value: unknown, nameOf: (id: unknown) => string | null): GoalCard["lastTouch"] {
  if (!isRecord(value)) return null;
  const name = nameOf(value.player);
  return name === null ? null : { name, team: asNumber(value.team) };
}

function lostBall(value: unknown, nameOf: (id: unknown) => string | null): LostBall | null {
  if (!isRecord(value)) return null;
  const ballY = asNumber(value.ball_y);
  const roles = Array.isArray(value.roles) ? value.roles : [];
  return {
    name: nameOf(value.player),
    beforeGoalS: asNumber(value.before_goal_s),
    ownHalf: ballY === null ? null : ballY < 0,
    roles: roles.flatMap((entry) => {
      if (!isRecord(entry)) return [];
      const name = nameOf(entry.player);
      const role = ROLES.find((known) => known === entry.role);
      return name === null || role === undefined ? [] : [{ name, role }];
    }),
  };
}

function defenders(value: unknown, nameOf: (id: unknown) => string | null): Defender[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry) => {
    if (!isRecord(entry)) return [];
    const name = nameOf(entry.player);
    if (name === null) return [];
    const distance = asNumber(entry.goal_distance);
    return [
      {
        name,
        distanceM: distance === null ? null : distance * METERS_PER_UU,
        boost: asNumber(entry.boost),
        demolished: entry.demolished === true,
        lastBack: entry.last_back === true,
      },
    ];
  });
}
