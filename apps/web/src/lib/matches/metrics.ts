/**
 * The metrics as the site shows them. The catalog comes from `rl_analysis` itself (`metrics.json`,
 * written by `just openapi`), so a metric cannot be computed and go unshown. The labels live in the
 * messages, under `metrics.<id>`.
 */
import catalog from "../../../metrics.json";

export type Unit = "%" | "%/min" | "/min" | "count" | "uu/s" | "uu";
export type Group = "boost" | "move" | "pos" | "event" | "touch";
export const GROUPS: readonly Group[] = ["boost", "move", "pos", "touch", "event"];

export interface MetricDefinition {
  id: string;
  unit: Unit;
  group: Group;
}

export const METRICS: readonly MetricDefinition[] = catalog.map((metric) => ({
  id: metric.id,
  unit: metric.unit as Unit,
  group: metric.id.split(".")[0] as Group,
}));

/** How a value reads on the page: game units turned into ones a player knows. */
export type DisplayUnit = "percent" | "perMinute" | "rate" | "count" | "kmh" | "meters";

export interface Shown {
  value: number;
  unit: DisplayUnit;
  digits: number;
}

// One Unreal unit is one centimeter: 2300 uu/s, the top speed, is 82.8 km/h.
const KMH_PER_UU_S = 0.036;
const METERS_PER_UU = 0.01;

/** The value to show, or null when there is none (a player without frames, a match in progress). */
export function show(value: number | null | undefined, unit: Unit): Shown | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  switch (unit) {
    case "%":
      return { value, unit: "percent", digits: 0 };
    case "%/min":
      return { value, unit: "perMinute", digits: 1 };
    case "/min":
      return { value, unit: "rate", digits: 1 };
    case "count":
      return { value, unit: "count", digits: 0 };
    case "uu/s":
      return { value: value * KMH_PER_UU_S, unit: "kmh", digits: 0 };
    case "uu":
      return { value: value * METERS_PER_UU, unit: "meters", digits: 1 };
  }
}
