/**
 * Where each file of a batch stands, as the player sees it. The API's statuses of the upload and
 * of its match fold into one phase.
 */
import type { Schemas } from "@/lib/api/client";

export type Phase =
  | "checking"
  | "waiting"
  | "sending"
  | "processing"
  | "ready"
  | "duplicate"
  | "partial"
  | "rejected"
  | "failed";

/** Phases after which nothing changes any more. */
export const FINAL: ReadonlySet<Phase> = new Set([
  "ready",
  "duplicate",
  "partial",
  "rejected",
  "failed",
]);

export interface Item {
  /** Stable within the page, for the list's keys. */
  key: string;
  name: string;
  size: number;
  phase: Phase;
  /** From 0 to 1 while sending. */
  progress: number;
  /** Why a file was rejected or failed: a key of the `upload.reasons` messages. */
  reason: string | null;
  uploadId: string | null;
  matchId: string | null;
}

type ServerUpload = Pick<Schemas["Upload"], "status" | "rejection" | "match_id" | "match_status">;

/** The phase of a file the API already holds, or null while it is still the browser's to send. */
export function phaseOf(upload: ServerUpload): Pick<Item, "phase" | "reason"> | null {
  switch (upload.status) {
    case "awaiting_file":
      return null;
    case "uploaded":
    case "processing":
      return { phase: "processing", reason: null };
    case "duplicate":
      return { phase: "duplicate", reason: null };
    case "rejected":
      return { phase: "rejected", reason: upload.rejection ?? "not_a_replay" };
    case "failed":
      return { phase: "failed", reason: "processing_failed" };
    case "done":
      switch (upload.match_status) {
        case "ready":
          return { phase: "ready", reason: null };
        case "header_only":
          return { phase: "partial", reason: null };
        case "failed":
          return { phase: "failed", reason: "processing_failed" };
        default:
          // Parsed, the analysis is still to come.
          return { phase: "processing", reason: null };
      }
  }
}

export const PHASES: readonly Phase[] = [
  "checking",
  "waiting",
  "sending",
  "processing",
  "ready",
  "duplicate",
  "partial",
  "rejected",
  "failed",
];

/** Every reason the page can show, each with its message in both languages. */
export const REASONS: readonly string[] = [
  "extension",
  "empty",
  "too_large",
  "not_a_replay",
  "corrupt",
  "size_mismatch",
  "read_failed",
  "send_failed",
  "processing_failed",
  "too_many_files",
  "quota_exceeded",
  "rate_limited",
  "bad_origin",
  "internal",
];

/** A reason the messages know, or the generic one. */
export function reasonKey(reason: string): string {
  return REASONS.includes(reason) ? reason : "internal";
}

export function summary(items: readonly Item[]): Record<Phase, number> {
  const counts = Object.fromEntries(PHASES.map((phase) => [phase, 0])) as Record<Phase, number>;
  for (const item of items) counts[item.phase] += 1;
  return counts;
}
