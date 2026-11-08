/**
 * The geometry of the history chart (T8.13): one metric over the last matches, oldest on the left.
 * Matches sit at even steps, whatever their dates: the chart answers "over my last N matches". A
 * match without a value leaves a gap in the line rather than a false slope.
 */
import type { Schemas } from "@/lib/api/client";

export interface Padding {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export const PADDING: Padding = { top: 12, right: 16, bottom: 12, left: 52 };

export interface Plotted {
  x: number;
  y: number;
  value: number;
  verified: boolean;
  matchId: string;
  playedAt: string | null;
}

export interface Geometry {
  points: Plotted[];
  /** SVG path data, broken where a match has no value; null without two points in a row. */
  path: string | null;
  /** Three gridlines, low to high. */
  ticks: { y: number; value: number }[];
}

/** The range to draw: the values with some room, never empty. */
export function domain(values: readonly number[]): [number, number] {
  const low = Math.min(...values);
  const high = Math.max(...values);
  if (high > low) {
    const room = (high - low) * 0.1;
    return [low - room, high + room];
  }
  const room = Math.abs(low) * 0.1 || 1;
  return [low - room, high + room];
}

export function geometry(
  history: readonly Schemas["HistoryPoint"][],
  width: number,
  height: number,
  padding: Padding = PADDING,
): Geometry {
  const values = history.flatMap((point) => (point.value === null ? [] : [point.value]));
  if (values.length === 0) return { points: [], path: null, ticks: [] };

  const [low, high] = domain(values);
  const plotWidth = Math.max(0, width - padding.left - padding.right);
  const plotHeight = Math.max(0, height - padding.top - padding.bottom);
  const xOf = (index: number) =>
    history.length === 1
      ? padding.left + plotWidth / 2
      : padding.left + (index * plotWidth) / (history.length - 1);
  const yOf = (value: number) => padding.top + ((high - value) / (high - low)) * plotHeight;

  const points: Plotted[] = [];
  const segments: string[] = [];
  let run: string[] = [];
  history.forEach((point, index) => {
    if (point.value === null) {
      if (run.length > 1) segments.push(run.join(" "));
      run = [];
      return;
    }
    const plotted = {
      x: xOf(index),
      y: yOf(point.value),
      value: point.value,
      verified: point.verified,
      matchId: point.match_id,
      playedAt: point.played_at,
    };
    points.push(plotted);
    run.push(`${run.length === 0 ? "M" : "L"}${plotted.x.toFixed(1)},${plotted.y.toFixed(1)}`);
  });
  if (run.length > 1) segments.push(run.join(" "));

  const ticks = [0, 0.5, 1].map((share) => {
    const value = low + share * (high - low);
    return { y: yOf(value), value };
  });
  return { points, path: segments.length > 0 ? segments.join(" ") : null, ticks };
}
