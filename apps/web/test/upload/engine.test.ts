import { describe, expect, it } from "vitest";
import { ApiError } from "../../src/lib/api/client";
import { type EngineOptions, runBatch } from "../../src/lib/upload/engine";
import type { Item } from "../../src/lib/upload/state";
import { FakeTransport, fakeTime, replayFile } from "./fakes";

function options(extra: Partial<EngineOptions> = {}) {
  const history: Item[][] = [];
  return {
    history,
    options: { ...fakeTime(), onChange: (items: Item[]) => history.push(items), ...extra },
  };
}

const phases = (items: Item[]) => items.map((item) => item.phase);

describe("a batch", () => {
  it("goes from the browser to a ready match", async () => {
    const transport = new FakeTransport();
    const { options: opts, history } = options();
    const items = await runBatch([replayFile("a.replay"), replayFile("b.replay")], transport, opts);
    expect(phases(items)).toEqual(["ready", "ready"]);
    expect(items.map((item) => item.matchId)).toEqual(["m-a.replay", "m-b.replay"]);
    expect(transport.sent.size).toBe(2);
    expect(transport.completed).toHaveLength(2);
    // Every phase was shown on the way.
    const seen = new Set(history.flatMap(phases));
    for (const phase of ["checking", "waiting", "sending", "processing", "ready"]) {
      expect(seen).toContain(phase);
    }
  });

  it("asks for all its URLs in one request, with each file's hash", async () => {
    const transport = new FakeTransport();
    await runBatch([replayFile("a.replay"), replayFile("b.replay")], transport, options().options);
    expect(transport.createdBatches).toHaveLength(1);
    expect(transport.createdBatches[0]?.map((file) => file.name)).toEqual(["a.replay", "b.replay"]);
    expect(transport.createdBatches[0]?.[0]?.sha256).toMatch(/^[0-9a-f]{64}$/);
  });

  it("never sends what the check refused", async () => {
    const transport = new FakeTransport();
    const fake = new File(["not a replay"], "fake.replay");
    const items = await runBatch([fake, replayFile("good.replay")], transport, options().options);
    expect(items[0]).toMatchObject({ phase: "rejected", reason: "not_a_replay" });
    expect(items[1]?.phase).toBe("ready");
    expect(transport.createdBatches[0]?.map((file) => file.name)).toEqual(["good.replay"]);
  });

  it("asks nothing of the API when every file is refused", async () => {
    const transport = new FakeTransport();
    const items = await runBatch([new File(["x"], "x.txt")], transport, options().options);
    expect(items[0]).toMatchObject({ phase: "rejected", reason: "extension" });
    expect(transport.createdBatches).toHaveLength(0);
  });

  it("sends three files at a time at most", async () => {
    const transport = new FakeTransport();
    const files = Array.from({ length: 8 }, (_, index) => replayFile(`${index}.replay`));
    await runBatch(files, transport, options().options);
    expect(transport.maxInFlight).toBeLessThanOrEqual(3);
    expect(transport.maxInFlight).toBeGreaterThan(1);
    expect(transport.sent.size).toBe(8);
  });

  it("does not send a file the API already has", async () => {
    const transport = new FakeTransport();
    transport.duplicates.add("old.replay");
    const items = await runBatch([replayFile("old.replay")], transport, options().options);
    expect(items[0]).toMatchObject({ phase: "duplicate", matchId: "m-old.replay" });
    expect(transport.sent.size).toBe(0);
  });

  it("explains a refusal of the whole batch", async () => {
    const transport = new FakeTransport();
    transport.createError = new ApiError(429, "quota_exceeded");
    const items = await runBatch([replayFile("a.replay")], transport, options().options);
    expect(items[0]).toMatchObject({ phase: "failed", reason: "quota_exceeded" });
  });

  it("calls an unknown error internal", async () => {
    const transport = new FakeTransport();
    transport.createError = new TypeError("Failed to fetch");
    const items = await runBatch([replayFile("a.replay")], transport, options().options);
    expect(items[0]).toMatchObject({ phase: "failed", reason: "internal" });
  });
});

describe("a transfer", () => {
  it("tries again after a network or store failure", async () => {
    const transport = new FakeTransport();
    transport.failures.set("a.replay", [0, 503]);
    const items = await runBatch([replayFile("a.replay")], transport, options().options);
    expect(items[0]?.phase).toBe("ready");
  });

  it("gives up after three tries", async () => {
    const transport = new FakeTransport();
    transport.failures.set("a.replay", [0, 0, 0]);
    const items = await runBatch([replayFile("a.replay")], transport, options().options);
    expect(items[0]).toMatchObject({ phase: "failed", reason: "send_failed" });
    expect(transport.completed).toHaveLength(0);
  });

  it("does not insist when the store refuses the URL", async () => {
    const transport = new FakeTransport();
    transport.failures.set("a.replay", [403, 0]);
    const items = await runBatch([replayFile("a.replay")], transport, options().options);
    expect(items[0]).toMatchObject({ phase: "failed", reason: "send_failed" });
    expect(transport.failures.get("a.replay")).toEqual([0]);
  });

  it("shows its progress", async () => {
    const transport = new FakeTransport();
    const { options: opts, history } = options();
    await runBatch([replayFile("a.replay")], transport, opts);
    const progress = history.map((items) => items[0]?.progress);
    expect(progress).toContain(0.5);
    expect(progress).toContain(1);
  });
});

describe("the word to the API", () => {
  it("is repeated while the store has not shown the file yet", async () => {
    const transport = new FakeTransport();
    transport.completeErrors.set("a.replay", [new ApiError(422, "object_missing")]);
    const items = await runBatch([replayFile("a.replay")], transport, options().options);
    expect(items[0]?.phase).toBe("ready");
  });

  it("reports a file that arrived with another size", async () => {
    const transport = new FakeTransport();
    transport.completeErrors.set("a.replay", [new ApiError(422, "size_mismatch")]);
    const items = await runBatch([replayFile("a.replay")], transport, options().options);
    expect(items[0]).toMatchObject({ phase: "rejected", reason: "size_mismatch" });
  });

  it("takes an upload already completed as done", async () => {
    const transport = new FakeTransport();
    transport.completeErrors.set("a.replay", [new ApiError(409, "invalid_state")]);
    const items = await runBatch([replayFile("a.replay")], transport, options().options);
    expect(items[0]?.phase).toBe("processing");
  });
});

describe("the processing", () => {
  it("ends in the outcome of each file", async () => {
    const transport = new FakeTransport();
    transport.outcome = (name) =>
      name === "partial.replay"
        ? { status: "done", rejection: null, match_status: "header_only" }
        : { status: "rejected", rejection: "corrupt", match_status: null };
    const items = await runBatch(
      [replayFile("partial.replay"), replayFile("broken.replay")],
      transport,
      options().options,
    );
    expect(items[0]?.phase).toBe("partial");
    expect(items[1]).toMatchObject({ phase: "rejected", reason: "corrupt" });
  });

  it("is followed for a while, then left to the matches page", async () => {
    const transport = new FakeTransport();
    transport.processingCalls = 1000;
    const time = fakeTime();
    const items = await runBatch([replayFile("slow.replay")], transport, {
      ...time,
      onChange: () => {},
      followForMs: 60_000,
    });
    expect(items[0]?.phase).toBe("processing");
    expect(time.now()).toBeGreaterThanOrEqual(60_000);
    expect(time.now()).toBeLessThan(80_000);
  });

  it("waits longer and longer between two checks", async () => {
    const transport = new FakeTransport();
    transport.processingCalls = 6;
    const waits: number[] = [];
    await runBatch([replayFile("a.replay")], transport, {
      onChange: () => {},
      sleep: async (ms) => {
        waits.push(ms);
      },
      pollMs: 2000,
      maxPollMs: 10_000,
    });
    expect(waits[0]).toBe(2000);
    expect(waits.at(-1)).toBe(10_000);
    for (let index = 1; index < waits.length; index += 1) {
      expect(waits[index]).toBeGreaterThanOrEqual(waits[index - 1] ?? 0);
    }
  });
});
