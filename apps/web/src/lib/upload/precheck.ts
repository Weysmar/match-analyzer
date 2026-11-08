/**
 * What the browser checks before sending anything: a comfort for the player, never a guarantee.
 * The worker checks every file again, as hostile (section 10 of CLAUDE.md).
 */

export const MAX_FILES = 50;
export const MAX_BYTES = 20 * 1024 * 1024;
/** The class name sits within the first bytes of the header, after a few integers. */
const HEAD_BYTES = 256;
const REPLAY_CLASS = new TextEncoder().encode("TAGame.Replay_");

export type Refusal = "extension" | "empty" | "too_large" | "not_a_replay";

/** Checks on the name and size alone, before reading a byte. */
export function checkFile(file: { name: string; size: number }): Refusal | null {
  if (!file.name.toLowerCase().endsWith(".replay")) return "extension";
  if (file.size === 0) return "empty";
  if (file.size > MAX_BYTES) return "too_large";
  return null;
}

/** Whether the first bytes of a file name a replay class, as the parser expects. */
export function looksLikeReplay(head: Uint8Array): boolean {
  outer: for (let start = 0; start + REPLAY_CLASS.length <= head.length; start += 1) {
    for (let index = 0; index < REPLAY_CLASS.length; index += 1) {
      if (head[start + index] !== REPLAY_CLASS[index]) continue outer;
    }
    return true;
  }
  return false;
}

export async function precheck(file: Blob & { name: string }): Promise<Refusal | null> {
  const refusal = checkFile(file);
  if (refusal) return refusal;
  const head = new Uint8Array(await file.slice(0, HEAD_BYTES).arrayBuffer());
  return looksLikeReplay(head) ? null : "not_a_replay";
}

/** A batch keeps its first files up to the limit; the others are counted, not sent. */
export function splitBatch<T>(files: readonly T[], max = MAX_FILES): { kept: T[]; left: number } {
  return { kept: files.slice(0, max), left: Math.max(0, files.length - max) };
}

export async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}
