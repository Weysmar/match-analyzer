import { describe, expect, it } from "vitest";
import { phaseOf, summary } from "../../src/lib/upload/state";

const base = { rejection: null, match_id: null, match_status: null } as const;

describe("the phase of a file the API holds", () => {
  it("is still the browser's while the file is awaited", () => {
    expect(phaseOf({ ...base, status: "awaiting_file" })).toBeNull();
  });

  it.each(["uploaded", "processing"] as const)("is processing once %s", (status) => {
    expect(phaseOf({ ...base, status })?.phase).toBe("processing");
  });

  it.each([
    ["pending", "processing"],
    ["parsing", "processing"],
    ["parsed", "processing"],
    ["analyzing", "processing"],
    ["ready", "ready"],
    ["header_only", "partial"],
    ["failed", "failed"],
  ] as const)("follows the match once parsed: %s gives %s", (matchStatus, phase) => {
    expect(
      phaseOf({ ...base, status: "done", match_id: "m", match_status: matchStatus })?.phase,
    ).toBe(phase);
  });

  it("is a duplicate when the match was already there", () => {
    expect(phaseOf({ ...base, status: "duplicate", match_id: "m" })?.phase).toBe("duplicate");
  });

  it("carries the reason of a rejection", () => {
    expect(phaseOf({ ...base, status: "rejected", rejection: "corrupt" })).toEqual({
      phase: "rejected",
      reason: "corrupt",
    });
  });

  it("calls a failure of the worker a processing failure", () => {
    expect(phaseOf({ ...base, status: "failed" })).toEqual({
      phase: "failed",
      reason: "processing_failed",
    });
  });
});

describe("the summary of a batch", () => {
  it("counts each phase", () => {
    const item = {
      key: "",
      name: "",
      size: 0,
      progress: 0,
      reason: null,
      uploadId: null,
      matchId: null,
    };
    const counts = summary([
      { ...item, phase: "ready" },
      { ...item, phase: "ready" },
      { ...item, phase: "failed" },
    ]);
    expect(counts.ready).toBe(2);
    expect(counts.failed).toBe(1);
    expect(counts.sending).toBe(0);
  });
});
