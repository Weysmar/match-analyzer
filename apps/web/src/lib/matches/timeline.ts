/**
 * Where the goals of a match sit on its timeline (T8.10). The analysis gives the game clock (A63):
 * seconds of play, overtime included. A match without it (read from its header only, or not
 * analyzed yet) falls back on the replay's own time, which also counts countdowns and
 * celebrations: the order holds, the clock does not, so no time is written then.
 */
import type { Schemas } from "@/lib/api/client";

export const REGULATION_S = 300;

export interface PlacedGoal {
  team: number | null;
  playerName: string | null;
  /** From 0 to 100, along the timeline. */
  left: number;
  overtime: boolean;
  /** Seconds left in regulation, or seconds into overtime; null without the game clock. */
  clockS: number | null;
  /** The score once this goal counts. */
  blue: number;
  orange: number;
}

export interface Timeline {
  goals: PlacedGoal[];
  onClock: boolean;
  /** Where overtime begins, from 0 to 100; null without overtime. */
  overtimeLeft: number | null;
}

type MatchClock = Pick<Schemas["MatchInfo"], "duration_s" | "game_length_s" | "overtime_from_s">;

const clamp = (value: number) => Math.min(100, Math.max(0, value));

export function placeGoals(goals: readonly Schemas["Goal"][], match: MatchClock): Timeline {
  const onClock = match.game_length_s !== null && goals.every((goal) => goal.game_time_s !== null);
  const overtimeFrom = onClock ? match.overtime_from_s : null;

  let axis: number;
  // Measured clocks run a few seconds long (A63): the regulation they show is scaled back to 300.
  let regulation: number;
  if (onClock) {
    const length = match.game_length_s ?? 0;
    axis = overtimeFrom !== null ? Math.max(length, overtimeFrom) : Math.max(length, REGULATION_S);
    regulation = overtimeFrom ?? Math.max(length, REGULATION_S);
  } else {
    const last = Math.max(0, ...goals.map((goal) => goal.time_s));
    axis = Math.max(match.duration_s ?? 0, last);
    regulation = axis;
  }

  let blue = 0;
  let orange = 0;
  const placed = goals.map((goal) => {
    if (goal.team === 0) blue += 1;
    if (goal.team === 1) orange += 1;
    const at = onClock ? (goal.game_time_s ?? 0) : goal.time_s;
    const overtime = overtimeFrom !== null && at > overtimeFrom;
    let clockS: number | null = null;
    if (onClock) {
      clockS = overtime
        ? at - (overtimeFrom ?? 0)
        : Math.max(0, REGULATION_S - (at * REGULATION_S) / regulation);
    }
    return {
      team: goal.team,
      playerName: goal.player_name,
      left: axis > 0 ? clamp((100 * at) / axis) : 0,
      overtime,
      clockS,
      blue,
      orange,
    };
  });
  return {
    goals: placed,
    onClock,
    overtimeLeft: overtimeFrom !== null && axis > 0 ? clamp((100 * overtimeFrom) / axis) : null,
  };
}

/** "m:ss", rounded to the second. */
export function formatClock(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
