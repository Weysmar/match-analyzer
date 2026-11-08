/**
 * Sends a batch of replays: check, hash, ask the API for one presigned URL per file, send each
 * file straight to the object store (three at a time), tell the API it arrived, then follow the
 * processing until every file is settled or the wait is over. The steps that talk to the network
 * come from a `Transport`, so the whole sequence runs in tests without a browser.
 */
import { ApiError, type Schemas } from "@/lib/api/client";
import { precheck, sha256Hex } from "./precheck";
import { FINAL, type Item, phaseOf } from "./state";

export type NamedBlob = Blob & { name: string };

/** A failed transfer to the object store. Status 0 means the network itself failed. */
export class SendError extends Error {
  constructor(readonly status: number) {
    super(`send failed: ${status}`);
  }
}

export interface Transport {
  create(files: Schemas["FileIn"][]): Promise<Schemas["UploadsCreated"]>;
  put(
    target: Schemas["UploadToSend"],
    file: Blob,
    onProgress: (fraction: number) => void,
  ): Promise<void>;
  complete(uploadId: string): Promise<void>;
  /** The owner's latest uploads, enough to cover one batch. */
  list(): Promise<Schemas["Upload"][]>;
}

export interface EngineOptions {
  onChange: (items: Item[]) => void;
  concurrency?: number;
  /** Tries per transfer, the first one included. */
  sendAttempts?: number;
  pollMs?: number;
  maxPollMs?: number;
  /** How long to follow the processing before leaving it to the matches page. */
  followForMs?: number;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
}

/** API errors the page knows how to explain; any other is called internal. */
const KNOWN_CODES = new Set([
  "too_large",
  "too_many_files",
  "quota_exceeded",
  "rate_limited",
  "bad_origin",
]);

function reasonOf(error: unknown): string {
  if (error instanceof ApiError && KNOWN_CODES.has(error.code)) return error.code;
  return "internal";
}

let created = 0;

export function newItems(files: readonly NamedBlob[]): Item[] {
  return files.map((file) => {
    created += 1;
    return {
      key: `${created}`,
      name: file.name,
      size: file.size,
      phase: "checking",
      progress: 0,
      reason: null,
      uploadId: null,
      matchId: null,
    };
  });
}

async function pool<T>(items: readonly T[], size: number, work: (item: T) => Promise<void>) {
  let next = 0;
  const workers = Array.from({ length: Math.min(size, items.length) }, async () => {
    while (next < items.length) {
      const item = items[next] as T;
      next += 1;
      await work(item);
    }
  });
  await Promise.all(workers);
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export async function runBatch(
  files: readonly NamedBlob[],
  transport: Transport,
  options: EngineOptions,
  items: Item[] = newItems(files),
): Promise<Item[]> {
  const sleep = options.sleep ?? defaultSleep;
  const now = options.now ?? Date.now;
  const emit = () => options.onChange(items.map((item) => ({ ...item })));
  const set = (item: Item, change: Partial<Item>) => {
    Object.assign(item, change);
    emit();
  };
  emit();

  // 1. Checks and hashes, one file at a time: they read whole files into memory.
  const accepted: { item: Item; file: NamedBlob; sha256: string }[] = [];
  for (const [index, file] of files.entries()) {
    const item = items[index] as Item;
    try {
      const refusal = await precheck(file);
      if (refusal) {
        set(item, { phase: "rejected", reason: refusal });
        continue;
      }
      accepted.push({ item, file, sha256: await sha256Hex(file) });
    } catch {
      set(item, { phase: "failed", reason: "read_failed" });
    }
  }
  if (accepted.length === 0) return items;

  // 2. One URL per file, in one request.
  let answers: Schemas["UploadsCreated"]["uploads"];
  try {
    answers = (
      await transport.create(
        accepted.map(({ file, sha256 }) => ({ name: file.name, size: file.size, sha256 })),
      )
    ).uploads;
  } catch (error) {
    const reason = reasonOf(error);
    for (const { item } of accepted) item.phase = "failed";
    for (const { item } of accepted) item.reason = reason;
    emit();
    return items;
  }

  const toSend: { item: Item; file: NamedBlob; target: Schemas["UploadToSend"] }[] = [];
  for (const [index, answer] of answers.entries()) {
    const entry = accepted[index];
    if (!entry) continue;
    if (answer.status === "duplicate") {
      Object.assign(entry.item, {
        phase: "duplicate",
        uploadId: answer.upload_id,
        matchId: answer.match_id,
      });
    } else {
      Object.assign(entry.item, { phase: "waiting", uploadId: answer.upload_id });
      toSend.push({ item: entry.item, file: entry.file, target: answer });
    }
  }
  emit();

  // 3. The transfers, then the word to the API.
  const attempts = options.sendAttempts ?? 3;
  await pool(toSend, options.concurrency ?? 3, async ({ item, file, target }) => {
    set(item, { phase: "sending", progress: 0 });
    for (let attempt = 1; ; attempt += 1) {
      try {
        let shown = 0;
        await transport.put(target, file, (fraction) => {
          // A redraw per percent is plenty.
          if (fraction - shown >= 0.01 || fraction === 1) {
            shown = fraction;
            set(item, { progress: fraction });
          }
        });
        break;
      } catch (error) {
        // An expired or refused URL will not get better; the network or the store may.
        const transient =
          !(error instanceof SendError) || error.status === 0 || error.status >= 500;
        if (!transient || attempt >= attempts) {
          set(item, { phase: "failed", reason: "send_failed" });
          return;
        }
        set(item, { progress: 0 });
        await sleep(1000 * attempt);
      }
    }
    for (let attempt = 1; ; attempt += 1) {
      try {
        await transport.complete(target.upload_id);
        set(item, { phase: "processing", progress: 1 });
        return;
      } catch (error) {
        if (error instanceof ApiError && error.code === "size_mismatch") {
          set(item, { phase: "rejected", reason: "size_mismatch" });
          return;
        }
        if (error instanceof ApiError && error.code === "invalid_state") {
          // Already completed, by an earlier try whose answer was lost.
          set(item, { phase: "processing", progress: 1 });
          return;
        }
        const retry =
          !(error instanceof ApiError) || error.code === "object_missing" || error.status >= 500;
        if (!retry || attempt >= attempts) {
          set(item, { phase: "failed", reason: reasonOf(error) });
          return;
        }
        await sleep(1000 * attempt);
      }
    }
  });

  // 4. Following the processing, by one request for the whole batch.
  const deadline = now() + (options.followForMs ?? 15 * 60_000);
  let interval = options.pollMs ?? 2000;
  while (items.some((item) => item.phase === "processing") && now() < deadline) {
    await sleep(interval);
    interval = Math.min(interval * 1.5, options.maxPollMs ?? 10_000);
    let latest: Schemas["Upload"][];
    try {
      latest = await transport.list();
    } catch {
      continue;
    }
    const byId = new Map(latest.map((upload) => [upload.upload_id, upload]));
    let changed = false;
    for (const item of items) {
      if (FINAL.has(item.phase) || item.uploadId === null) continue;
      const upload = byId.get(item.uploadId);
      const phase = upload ? phaseOf(upload) : null;
      if (!upload || !phase) continue;
      if (phase.phase !== item.phase || upload.match_id !== item.matchId) {
        Object.assign(item, phase, { matchId: upload.match_id });
        changed = true;
      }
    }
    if (changed) emit();
  }
  return items;
}
