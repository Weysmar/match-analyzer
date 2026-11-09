/**
 * The metrics as the site shows them. The catalog comes from `rl_analysis` itself (`metrics.json`,
 * written by `just openapi`), so a metric cannot be computed and go unshown. The labels live in the
 * messages, under `metrics.<id>`.
 */
import catalog from "../../../metrics.json";

export type Unit = "%" | "%/min" | "/min" | "count" | "uu/s" | "uu" | "s";
export type Group = "boost" | "move" | "pos" | "touch" | "poss" | "kick" | "event";
export const GROUPS: readonly Group[] = ["boost", "move", "pos", "touch", "poss", "kick", "event"];

export interface MetricDefinition {
  id: string;
  unit: Unit;
  group: Group;
}

function definition(metric: (typeof catalog)[number]): MetricDefinition {
  return { id: metric.id, unit: metric.unit as Unit, group: metric.id.split(".")[0] as Group };
}

/** A value per player: the rows of the metrics table, and of "my stats". */
export const METRICS: readonly MetricDefinition[] = catalog
  .filter((metric) => metric.scope === "player")
  .map(definition);

/** A value per team, like possession: shown on its own, a player row would mean nothing. */
export const TEAM_METRICS: readonly MetricDefinition[] = catalog
  .filter((metric) => metric.scope === "team")
  .map(definition);

export interface PossessionSplit {
  blue: number;
  orange: number;
  loose: number;
}

/**
 * Live play split between the teams and the loose ball, in %, or null without possession (a match
 * parsed before touches were detected). The loose ball is what neither team holds.
 */
export function possessionSplit(
  teamMetrics: Record<string, Record<string, number | null>>,
): PossessionSplit | null {
  const blue = teamMetrics["0"]?.["poss.team_pct"];
  const orange = teamMetrics["1"]?.["poss.team_pct"];
  if (typeof blue !== "number" || typeof orange !== "number") return null;
  return { blue, orange, loose: Math.max(0, 100 - blue - orange) };
}

/** Goals each team conceded within 12 s of a kickoff, or null without kickoffs (T13.2). */
export function kickoffGoals(
  teamMetrics: Record<string, Record<string, number | null>>,
): { blue: number; orange: number } | null {
  const blue = teamMetrics["0"]?.["kick.goals_conceded"];
  const orange = teamMetrics["1"]?.["kick.goals_conceded"];
  if (typeof blue !== "number" || typeof orange !== "number") return null;
  return { blue, orange };
}

/** How a value reads on the page: game units turned into ones a player knows. */
export type DisplayUnit = "percent" | "perMinute" | "rate" | "count" | "kmh" | "meters" | "seconds";

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
    case "s":
      return { value, unit: "seconds", digits: 2 };
  }
}
