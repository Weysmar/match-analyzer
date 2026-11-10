/**
 * The two blind reviews of the labeling mode, in development only, next to the verdicts on
 * detections (`labels.ts`):
 *
 * - the goals conceded (T15.4): for each goal, every tag judged there or not, without the tags the
 *   analysis gave it, which only go into the file for `just v2-report`;
 * - windows of play (T17.1): 10 s before each goal and a few drawn at random, each detector judged
 *   there or not, without the detections, which likewise only go into the file.
 *
 * `just v2-report` turns them into each tag's precision and recall, and each detector's recall.
 */
import { GOAL_TAGS, type GoalTag } from "@/lib/matches/conceded";
import type { Match2d } from "./document";
import { type LabelFile, parseLabelFile, shuffled, VERDICTS, type Verdict } from "./labels";
import { clockAt, durationS } from "./time";

/** The detectors whose recall the windows measure: kickoffs and duels are subtr-actor's. */
export const RECALL_DETECTORS = ["turnover", "double_commit", "overcommit"] as const;
export type RecallDetector = (typeof RECALL_DETECTORS)[number];
/** As long as a goal's context (`GOAL_CONTEXT_WINDOW`). */
export const WINDOW_S = 10;
/** Windows drawn at random in each match, besides those before its goals. */
export const RANDOM_WINDOWS = 4;

const round = (value: number, digits: number) => Math.round(value * 10 ** digits) / 10 ** digits;

export interface GoalItem {
  /** The goal's replay time: it names the goal. */
  timeS: number;
  /** Seconds of play at the goal, and how far back its context goes. */
  clockS: number;
  windowS: number;
  /** What the analysis found: never shown during the review. */
  detected: GoalTag[];
}

export type TagVerdicts = Partial<Record<GoalTag, Verdict>>;

export interface GoalLabelFile {
  version: 1;
  match_id: string;
  kind: "goals";
  labeled_at: string;
  goals: { time_s: number; clock_s: number; detected: GoalTag[]; verdicts: TagVerdicts }[];
}

/** The goals of a match to review, shuffled the same way on every visit. */
export function goalQueue(goals: readonly GoalItem[], seed: string): GoalItem[] {
  return shuffled([...goals], `${seed}:goals`);
}

/** The file of the goals reviewed: only those with at least one verdict. */
export function goalLabelFile(
  matchId: string,
  queue: readonly GoalItem[],
  verdicts: ReadonlyMap<number, TagVerdicts>,
  now: Date,
): GoalLabelFile {
  return {
    version: 1,
    match_id: matchId,
    kind: "goals",
    labeled_at: now.toISOString(),
    goals: queue.flatMap((goal, index) => {
      const given = verdicts.get(index);
      return given && Object.keys(given).length > 0
        ? [
            {
              time_s: round(goal.timeS, 3),
              clock_s: round(goal.clockS, 1),
              detected: GOAL_TAGS.filter((tag) => goal.detected.includes(tag)),
              verdicts: given,
            },
          ]
        : [];
    }),
  };
}

export interface WindowItem {
  startClockS: number;
  endClockS: number;
  source: "before_goal" | "random";
  /** Whether each detector found one in the window: never shown during the review. */
  detected: Record<RecallDetector, boolean>;
}

export type DetectorVerdicts = Partial<Record<RecallDetector, Verdict>>;

export interface WindowLabelFile {
  version: 1;
  match_id: string;
  kind: "windows";
  labeled_at: string;
  windows: {
    start_clock_s: number;
    end_clock_s: number;
    source: WindowItem["source"];
    detected: Record<RecallDetector, boolean>;
    verdicts: DetectorVerdicts;
  }[];
}

/** A repeatable random sequence from a string (FNV-1a, then mulberry32). */
function randomOf(seed: string): () => number {
  let state = 2166136261;
  for (const character of seed) {
    state ^= character.codePointAt(0) ?? 0;
    state = Math.imul(state, 16777619);
  }
  state >>>= 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let mixed = Math.imul(state ^ (state >>> 15), 1 | state);
    mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed;
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * The windows of play to judge: the 10 s before each goal, where a mistake is likelier, then
 * `RANDOM_WINDOWS` drawn at random elsewhere in the play, none overlapping; shuffled.
 */
export function recallWindows(view: Match2d, seed: string): WindowItem[] {
  const length = clockAt(view, durationS(view));
  if (length < WINDOW_S) return [];
  const found = (view.situations ?? []).map((situation) => ({
    kind: situation.kind,
    clockS: clockAt(view, situation.t),
  }));
  const window = (start: number, source: WindowItem["source"]): WindowItem => {
    const startClockS = round(start, 1);
    const endClockS = round(start + WINDOW_S, 1);
    const detected = Object.fromEntries(
      RECALL_DETECTORS.map((detector) => [
        detector,
        found.some(
          (situation) =>
            situation.kind === detector &&
            situation.clockS >= startClockS &&
            situation.clockS <= endClockS,
        ),
      ]),
    ) as Record<RecallDetector, boolean>;
    return { startClockS, endClockS, source, detected };
  };
  const overlaps = (start: number, taken: readonly WindowItem[]) =>
    taken.some((other) => start < other.endClockS && start + WINDOW_S > other.startClockS);

  const windows: WindowItem[] = [];
  for (const goal of view.goals) {
    const start = Math.max(0, clockAt(view, goal.t) - WINDOW_S);
    if (!overlaps(start, windows)) windows.push(window(start, "before_goal"));
  }
  const next = randomOf(`${seed}:windows`);
  let drawn = 0;
  for (let attempt = 0; attempt < 100 && drawn < RANDOM_WINDOWS; attempt += 1) {
    const start = next() * (length - WINDOW_S);
    if (overlaps(start, windows)) continue;
    windows.push(window(start, "random"));
    drawn += 1;
  }
  return shuffled(windows, `${seed}:order`);
}

/** The file of the windows judged: only those with at least one verdict. */
export function windowLabelFile(
  matchId: string,
  queue: readonly WindowItem[],
  verdicts: ReadonlyMap<number, DetectorVerdicts>,
  now: Date,
): WindowLabelFile {
  return {
    version: 1,
    match_id: matchId,
    kind: "windows",
    labeled_at: now.toISOString(),
    windows: queue.flatMap((item, index) => {
      const given = verdicts.get(index);
      return given && Object.keys(given).length > 0
        ? [
            {
              start_clock_s: item.startClockS,
              end_clock_s: item.endClockS,
              source: item.source,
              detected: item.detected,
              verdicts: given,
            },
          ]
        : [];
    }),
  };
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isVerdict = (value: unknown) => VERDICTS.includes(value as Verdict);
const isClock = (value: unknown) => typeof value === "number" && value >= 0;

function verdictsOf(value: unknown, keys: readonly string[]): boolean {
  return (
    isRecord(value) &&
    Object.entries(value).every(([key, verdict]) => keys.includes(key) && isVerdict(verdict))
  );
}

/** A goals file as the schema has it, or false. */
export function isGoalLabelFile(file: Record<string, unknown>): boolean {
  return (
    file.kind === "goals" &&
    Object.keys(file).length === 5 &&
    Array.isArray(file.goals) &&
    file.goals.every(
      (goal) =>
        isRecord(goal) &&
        Object.keys(goal).length === 4 &&
        isClock(goal.time_s) &&
        isClock(goal.clock_s) &&
        Array.isArray(goal.detected) &&
        goal.detected.every((tag) => GOAL_TAGS.includes(tag as GoalTag)) &&
        new Set(goal.detected).size === goal.detected.length &&
        verdictsOf(goal.verdicts, GOAL_TAGS),
    )
  );
}

/** A windows file as the schema has it, or false. */
export function isWindowLabelFile(file: Record<string, unknown>): boolean {
  return (
    file.kind === "windows" &&
    Object.keys(file).length === 5 &&
    Array.isArray(file.windows) &&
    file.windows.every(
      (window) =>
        isRecord(window) &&
        Object.keys(window).length === 5 &&
        isClock(window.start_clock_s) &&
        isClock(window.end_clock_s) &&
        (window.source === "before_goal" || window.source === "random") &&
        isRecord(window.detected) &&
        Object.entries(window.detected).every(
          ([key, value]) =>
            RECALL_DETECTORS.includes(key as RecallDetector) && typeof value === "boolean",
        ) &&
        verdictsOf(window.verdicts, RECALL_DETECTORS),
    )
  );
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export type AnyLabelFile = LabelFile | GoalLabelFile | WindowLabelFile;

/** Any of the three kinds of label file, as the schema has it, or null: what the export writes. */
export function parseAnyLabelFile(value: unknown): AnyLabelFile | null {
  if (!isRecord(value)) return null;
  if (!("kind" in value)) return parseLabelFile(value);
  const header =
    value.version === 1 &&
    typeof value.match_id === "string" &&
    UUID.test(value.match_id) &&
    typeof value.labeled_at === "string" &&
    !Number.isNaN(Date.parse(value.labeled_at));
  if (header && isGoalLabelFile(value)) return value as unknown as GoalLabelFile;
  if (header && isWindowLabelFile(value)) return value as unknown as WindowLabelFile;
  return null;
}

/** Where a file goes in `tests/fixtures/labels/`: its match and kind, nothing from outside. */
export function anyFileName(file: AnyLabelFile): string {
  return "kind" in file
    ? `${file.match_id}-${file.kind}.json`
    : `${file.match_id}-${file.detector}.json`;
}
