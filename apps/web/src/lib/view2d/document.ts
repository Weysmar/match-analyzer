/**
 * The 2D view's document (`match2d`, `packages/schemas/match2d.schema.json`), as the player uses
 * it: decoded once, every series absolute. The analysis writes positions and the clock as
 * differences from one sample to the next, which gzip packs well (B12 of docs/PLAN-V2.md).
 */

export const VERSION = 1;
/** Bits of a car's `flags`. */
export const SHOWN = 1;
export const DEMOLISHED = 2;
export const BOOSTING = 4;

export interface Car {
  /** `match_player_id`: the name comes from the match sheet. */
  id: number;
  team: 0 | 1;
  x: number[];
  y: number[];
  z: number[];
  /** Degrees, 0 towards +x, 90 towards +y. */
  yaw: number[];
  boost: number[];
  flags: number[];
}

export interface TimedEvent {
  /** Seconds since the first sample. */
  t: number;
}

export const SITUATION_KINDS = ["turnover", "kickoff", "fifty_fifty", "double_commit"] as const;
export type SituationKind = (typeof SITUATION_KINDS)[number];

/** What a detection found (`situations` of match2d): turnovers, kickoffs, duels, double commits. */
export interface Situation extends TimedEvent {
  kind: SituationKind;
  team: 0 | 1 | null;
  /** `match_player_id`, the one who acted first. */
  players: number[];
}

export interface Match2d {
  rateHz: number;
  /** The replay's time of the first sample, in seconds. */
  startS: number;
  samples: number;
  /** Seconds of play: the game clock runs in live play only. */
  clockS: number[];
  phase: number[];
  ball: { x: number[]; y: number[]; z: number[] };
  cars: Car[];
  goals: (TimedEvent & { team: 0 | 1 | null; player: number | null })[];
  demolitions: (TimedEvent & { attacker: number | null; victim: number | null })[];
  touches: (TimedEvent & { player: number })[] | null;
  /** Null without detected touches. */
  situations: Situation[] | null;
}

export class ViewFormatError extends Error {}

type Raw = Record<string, unknown>;

function isObject(value: unknown): value is Raw {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function series(value: unknown, length: number, name: string): number[] {
  if (!Array.isArray(value) || value.length !== length || !value.every(Number.isFinite)) {
    throw new ViewFormatError(`bad series: ${name}`);
  }
  return value as number[];
}

/** The running sum: the first value, then each one plus the previous. */
export function undelta(values: readonly number[]): number[] {
  let total = 0;
  return values.map((value) => {
    total += value;
    return total;
  });
}

function list(value: unknown, name: string): Raw[] {
  if (!Array.isArray(value) || !value.every(isObject))
    throw new ViewFormatError(`bad list: ${name}`);
  return value;
}

const number = (value: unknown): number => (typeof value === "number" ? value : 0);
const nullableNumber = (value: unknown): number | null =>
  typeof value === "number" ? value : null;
const team = (value: unknown): 0 | 1 | null => (value === 0 || value === 1 ? value : null);

/** Checks the shape the player relies on and decodes the differences. */
export function decode(raw: unknown): Match2d {
  if (!isObject(raw) || raw.version !== VERSION) throw new ViewFormatError("unknown version");
  const samples = raw.samples;
  const rateHz = raw.rate_hz;
  if (typeof samples !== "number" || samples < 1 || typeof rateHz !== "number" || rateHz <= 0) {
    throw new ViewFormatError("bad grid");
  }
  const delta = new Set(Array.isArray(raw.delta) ? raw.delta : []);
  const read = (value: unknown, name: string) => {
    const values = series(value, samples, name);
    return delta.has(name) ? undelta(values) : values;
  };
  const startS = number(raw.start_s);
  const since = (time: unknown) => number(time) - startS;
  if (!isObject(raw.ball)) throw new ViewFormatError("bad ball");
  const ball = raw.ball;
  const touches = raw.touches === null ? null : list(raw.touches, "touches");
  const situations =
    raw.situations === null || raw.situations === undefined
      ? null
      : list(raw.situations, "situations");

  return {
    rateHz,
    startS,
    samples,
    clockS: read(raw.clock_ds, "clock_ds").map((tenths) => tenths / 10),
    phase: read(raw.phase, "phase"),
    ball: { x: read(ball.x, "ball.x"), y: read(ball.y, "ball.y"), z: read(ball.z, "ball.z") },
    cars: list(raw.players, "players").map((player) => ({
      id: number(player.id),
      team: team(player.team) ?? 0,
      x: read(player.x, "players.x"),
      y: read(player.y, "players.y"),
      z: read(player.z, "players.z"),
      yaw: read(player.yaw, "players.yaw"),
      boost: read(player.boost, "players.boost"),
      flags: read(player.flags, "players.flags"),
    })),
    goals: list(raw.goals, "goals").map((goal) => ({
      t: since(goal.time_s),
      team: team(goal.team),
      player: nullableNumber(goal.player),
    })),
    demolitions: list(raw.demolitions, "demolitions").map((demo) => ({
      t: since(demo.time_s),
      attacker: nullableNumber(demo.attacker),
      victim: nullableNumber(demo.victim),
    })),
    touches:
      touches === null
        ? null
        : touches.map((touch) => ({ t: since(touch.time_s), player: number(touch.player) })),
    situations:
      situations === null
        ? null
        : situations
            .filter((situation) => SITUATION_KINDS.includes(situation.kind as SituationKind))
            .map((situation) => ({
              kind: situation.kind as SituationKind,
              t: since(situation.time_s),
              team: team(situation.team),
              players: Array.isArray(situation.players)
                ? situation.players.filter((id): id is number => typeof id === "number")
                : [],
            })),
  };
}

/**
 * The document behind a presigned URL: fetched straight from the object store, unpacked here.
 * It is stored as `application/gzip`, without `Content-Encoding`, so no store unpacks it on the way.
 */
export async function loadView(url: string, fetcher: typeof fetch = fetch): Promise<Match2d> {
  const response = await fetcher(url);
  if (!response.ok || response.body === null) throw new ViewFormatError(`http ${response.status}`);
  const unpacked = response.body.pipeThrough(new DecompressionStream("gzip"));
  const text = await new Response(unpacked).text();
  return decode(JSON.parse(text));
}
