/**
 * The labeling mode (T12.7 of docs/PLAN-V2.md, DV4), in development only: the detected situations
 * of a match one by one, in a shuffled order, each judged "true", "false" or "uncertain" from the 2D
 * view. The verdicts go to `tests/fixtures/labels/` (`packages/schemas/labels.schema.json`), which
 * `just v2-report` reads to measure each detector's precision.
 */
import type { Match2d } from "./document";
import { clockAt } from "./time";

export const DETECTORS = [
  "turnover",
  "kickoff",
  "fifty_fifty",
  "double_commit",
  "overcommit",
] as const;
export type Detector = (typeof DETECTORS)[number];
export const VERDICTS = ["true", "false", "uncertain"] as const;
export type Verdict = (typeof VERDICTS)[number];

export interface QueueItem {
  detector: Detector;
  /** The player's time. */
  t: number;
  /** The replay's time, as the analysis wrote it: it names the situation. */
  timeS: number;
  clockS: number;
  team: 0 | 1 | null;
  players: number[];
}

export interface LabelFile {
  version: 1;
  match_id: string;
  detector: Detector;
  labeled_at: string;
  labels: { time_s: number; clock_s: number; verdict: Verdict }[];
}

const round = (value: number, digits: number) => Math.round(value * 10 ** digits) / 10 ** digits;

/** A number from a string, always the same for the same string (FNV-1a). */
function hash(text: string): number {
  let value = 2166136261;
  for (const character of text) {
    value ^= character.codePointAt(0) ?? 0;
    value = Math.imul(value, 16777619);
  }
  return value >>> 0;
}

/** A repeatable random sequence from a seed (mulberry32). */
function random(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let mixed = Math.imul(state ^ (state >>> 15), 1 | state);
    mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed;
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * The match's situations to judge, shuffled (section 4: detections drawn at random, so that one
 * situation does not colour the judgment of the next), the same order on every visit.
 */
export function labelQueue(view: Match2d, seed: string): QueueItem[] {
  const items: QueueItem[] = (view.situations ?? []).map((situation) => ({
    detector: situation.kind,
    t: situation.t,
    timeS: round(situation.t + view.startS, 3),
    clockS: round(clockAt(view, situation.t), 1),
    team: situation.team,
    players: situation.players,
  }));
  const next = random(hash(seed));
  for (let index = items.length - 1; index > 0; index -= 1) {
    const other = Math.floor(next() * (index + 1));
    [items[index], items[other]] = [items[other] as QueueItem, items[index] as QueueItem];
  }
  return items;
}

/** The file of one detector's verdicts on this match: only the situations judged. */
export function labelFile(
  matchId: string,
  detector: Detector,
  queue: readonly QueueItem[],
  verdicts: ReadonlyMap<number, Verdict>,
  now: Date,
): LabelFile {
  return {
    version: 1,
    match_id: matchId,
    detector,
    labeled_at: now.toISOString(),
    labels: queue.flatMap((item, index) => {
      const verdict = verdicts.get(index);
      return item.detector === detector && verdict
        ? [{ time_s: item.timeS, clock_s: item.clockS, verdict }]
        : [];
    }),
  };
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function isLabel(value: unknown): value is LabelFile["labels"][number] {
  if (typeof value !== "object" || value === null) return false;
  const label = value as Record<string, unknown>;
  return (
    Object.keys(label).length === 3 &&
    typeof label.time_s === "number" &&
    label.time_s >= 0 &&
    typeof label.clock_s === "number" &&
    label.clock_s >= 0 &&
    VERDICTS.includes(label.verdict as Verdict)
  );
}

/** A label file as the schema has it, or null: what the export accepts to write. */
export function parseLabelFile(value: unknown): LabelFile | null {
  if (typeof value !== "object" || value === null) return null;
  const file = value as Record<string, unknown>;
  const valid =
    Object.keys(file).length === 5 &&
    file.version === 1 &&
    typeof file.match_id === "string" &&
    UUID.test(file.match_id) &&
    DETECTORS.includes(file.detector as Detector) &&
    typeof file.labeled_at === "string" &&
    !Number.isNaN(Date.parse(file.labeled_at)) &&
    Array.isArray(file.labels) &&
    file.labels.every(isLabel);
  return valid ? (file as unknown as LabelFile) : null;
}

/** Where a file goes in `tests/fixtures/labels/`: its match and detector, nothing from outside. */
export function fileNameOf(file: LabelFile): string {
  return `${file.match_id}-${file.detector}.json`;
}
