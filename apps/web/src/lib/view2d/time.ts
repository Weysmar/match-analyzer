/**
 * Time in the 2D view. The player's time `t` counts seconds since the document's first sample, on
 * the replay's own clock; sample `i` sits at `i / rateHz`. The game clock, which only runs in live
 * play, is what the cursor shows (section 5.6 of docs/PLAN-V2.md).
 */
import type { Match2d } from "./document";

/** Where `t` falls: the sample at or before it, and how far towards the next one (0 to 1). */
export interface Position {
  index: number;
  fraction: number;
}

export function durationS(view: Pick<Match2d, "samples" | "rateHz">): number {
  return (view.samples - 1) / view.rateHz;
}

export function clampTime(view: Pick<Match2d, "samples" | "rateHz">, t: number): number {
  return Math.min(durationS(view), Math.max(0, Number.isFinite(t) ? t : 0));
}

export function positionAt(view: Pick<Match2d, "samples" | "rateHz">, t: number): Position {
  const exact = clampTime(view, t) * view.rateHz;
  const index = Math.min(view.samples - 1, Math.floor(exact));
  return { index, fraction: index >= view.samples - 1 ? 0 : exact - index };
}

export function timeOfSample(view: Pick<Match2d, "rateHz">, index: number): number {
  return index / view.rateHz;
}

/** A series at a position, linear between its two samples. */
export function lerp(values: readonly number[], { index, fraction }: Position): number {
  const a = values[index] ?? 0;
  const b = values[index + 1] ?? a;
  return a + (b - a) * fraction;
}

/** An angle in degrees at a position, turning the short way round. */
export function lerpAngle(values: readonly number[], { index, fraction }: Position): number {
  const a = values[index] ?? 0;
  const b = values[index + 1] ?? a;
  const turn = ((((b - a) % 360) + 540) % 360) - 180;
  return a + turn * fraction;
}

/** Seconds of play at `t`. */
export function clockAt(view: Match2d, t: number): number {
  return lerp(view.clockS, positionAt(view, t));
}

/** The first time the game clock reaches `clockS`: where the cursor sends the player. */
export function timeAtClock(view: Match2d, clockS: number): number {
  const clock = view.clockS;
  let low = 0;
  let high = clock.length - 1;
  if (clockS <= (clock[0] ?? 0)) return 0;
  if (clockS >= (clock[high] ?? 0)) return timeOfSample(view, high);
  // The first sample at or past `clockS`, then back between it and the one before.
  while (low < high) {
    const middle = (low + high) >> 1;
    if ((clock[middle] ?? 0) < clockS) low = middle + 1;
    else high = middle;
  }
  const before = clock[low - 1] ?? 0;
  const after = clock[low] ?? before;
  const fraction = after > before ? (clockS - before) / (after - before) : 0;
  return timeOfSample(view, low - 1 + fraction);
}

/** Where each goal sits along the cursor, from 0 to 100, with its team (T12.5). */
export function goalMarkers(view: Match2d): { left: number; team: 0 | 1 | null }[] {
  const last = view.clockS[view.clockS.length - 1] ?? 0;
  if (last <= 0) return [];
  return view.goals.map((goal) => ({
    left: Math.min(100, Math.max(0, (100 * clockAt(view, goal.t)) / last)),
    team: goal.team,
  }));
}

/** Where each situation sits along the cursor, from 0 to 100, with its kind (T13.4). */
export function situationMarkers(
  view: Match2d,
): { left: number; kind: NonNullable<Match2d["situations"]>[number]["kind"] }[] {
  const last = view.clockS[view.clockS.length - 1] ?? 0;
  if (last <= 0 || view.situations === null) return [];
  return view.situations.map((situation) => ({
    left: Math.min(100, Math.max(0, (100 * clockAt(view, situation.t)) / last)),
    kind: situation.kind,
  }));
}

/** A replay time, such as a goal's on the match sheet, as the player's time. */
export function fromReplayTime(view: Pick<Match2d, "startS">, replayS: number): number {
  return replayS - view.startS;
}
