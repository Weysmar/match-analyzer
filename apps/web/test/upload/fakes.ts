import type { Schemas } from "../../src/lib/api/client";
import { type NamedBlob, SendError, type Transport } from "../../src/lib/upload/engine";

/** The first bytes of a replay as the game writes them: sizes, CRC, versions, then the class. */
export function replayBytes(size = 2048): Uint8Array<ArrayBuffer> {
  const bytes = new Uint8Array(size);
  const header = new TextEncoder().encode("TAGame.Replay_Soccar_TA\0");
  bytes.set([0x10, 0x27, 0, 0, 0xaa, 0xbb, 0xcc, 0xdd, 0x86, 3, 0, 0, 0x22, 0, 0, 0], 0);
  bytes.set([0x18, 0, 0, 0], 16);
  bytes.set(header, 20);
  return bytes;
}

export function replayFile(name = "match.replay", size = 2048): NamedBlob {
  return new File([replayBytes(size)], name);
}

type Upload = Schemas["Upload"];

/**
 * A pretend API and object store. Each upload is processed over a few `list` calls, as the worker
 * would, and ends in `outcome`.
 */
export class FakeTransport implements Transport {
  readonly sent = new Map<string, Blob>();
  readonly completed: string[] = [];
  readonly createdBatches: Schemas["FileIn"][][] = [];
  inFlight = 0;
  maxInFlight = 0;
  /** Transfers failing before one goes through, per file name. */
  failures = new Map<string, number[]>();
  /** `complete` answers, per file name, before the call that works. */
  completeErrors = new Map<string, Error[]>();
  createError: Error | null = null;
  duplicates = new Set<string>();
  outcome: (name: string) => Pick<Upload, "status" | "rejection" | "match_status"> = () => ({
    status: "done",
    rejection: null,
    match_status: "ready",
  });
  /** How many `list` calls a file spends in processing before its outcome. */
  processingCalls = 2;
  private readonly names = new Map<string, string>();
  private readonly seen = new Map<string, number>();

  async create(files: Schemas["FileIn"][]): Promise<Schemas["UploadsCreated"]> {
    this.createdBatches.push(files);
    if (this.createError) throw this.createError;
    return {
      uploads: files.map((file, index) => {
        const uploadId = `u-${this.names.size}-${index}`;
        this.names.set(uploadId, file.name);
        if (this.duplicates.has(file.name)) {
          return { upload_id: uploadId, status: "duplicate", match_id: `m-${file.name}` };
        }
        return {
          upload_id: uploadId,
          status: "awaiting_file",
          url: `https://store.test/incoming/${uploadId}`,
          method: "PUT",
          headers: { "Content-Type": "application/octet-stream" },
          expires_at: "2026-11-08T12:00:00Z",
        };
      }),
    };
  }

  async put(
    target: Schemas["UploadToSend"],
    file: Blob,
    onProgress: (fraction: number) => void,
  ): Promise<void> {
    this.inFlight += 1;
    this.maxInFlight = Math.max(this.maxInFlight, this.inFlight);
    try {
      await Promise.resolve();
      const name = this.names.get(target.upload_id) ?? "";
      const pending = this.failures.get(name);
      const status = pending?.shift();
      if (status !== undefined) throw new SendError(status);
      onProgress(0.5);
      onProgress(1);
      this.sent.set(target.upload_id, file);
    } finally {
      this.inFlight -= 1;
    }
  }

  async complete(uploadId: string): Promise<void> {
    const name = this.names.get(uploadId) ?? "";
    const error = this.completeErrors.get(name)?.shift();
    if (error) throw error;
    this.completed.push(uploadId);
  }

  async list(): Promise<Upload[]> {
    return this.completed.map((uploadId) => {
      const calls = (this.seen.get(uploadId) ?? 0) + 1;
      this.seen.set(uploadId, calls);
      const name = this.names.get(uploadId) ?? "";
      const base = { upload_id: uploadId, name, match_id: `m-${name}` };
      if (calls <= this.processingCalls) {
        return {
          ...base,
          status: "processing",
          rejection: null,
          match_status: null,
          match_id: null,
        };
      }
      return { ...base, ...this.outcome(name) };
    });
  }
}

/** No waiting in tests; the clock moves by what was slept. */
export function fakeTime() {
  let clock = 0;
  return {
    sleep: async (ms: number) => {
      clock += ms;
    },
    now: () => clock,
  };
}
