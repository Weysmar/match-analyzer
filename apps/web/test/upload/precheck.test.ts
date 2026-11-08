import { describe, expect, it } from "vitest";
import {
  checkFile,
  looksLikeReplay,
  MAX_BYTES,
  MAX_FILES,
  precheck,
  sha256Hex,
  splitBatch,
} from "../../src/lib/upload/precheck";
import { replayBytes, replayFile } from "./fakes";

describe("the check before sending", () => {
  it("accepts a replay", async () => {
    expect(await precheck(replayFile())).toBeNull();
  });

  it("accepts the extension in any case", async () => {
    expect(await precheck(replayFile("MATCH.REPLAY"))).toBeNull();
  });

  it("refuses a fake replay: right name, wrong content", async () => {
    const fake = new File(
      [new TextEncoder().encode("PK\u0003\u0004 not a replay at all")],
      "x.replay",
    );
    expect(await precheck(fake)).toBe("not_a_replay");
  });

  it("refuses another kind of file", async () => {
    expect(await precheck(new File([replayBytes()], "match.zip"))).toBe("extension");
  });

  it("refuses an empty file", async () => {
    expect(await precheck(new File([], "empty.replay"))).toBe("empty");
  });

  it("refuses a file over 20 MB without reading it", () => {
    expect(checkFile({ name: "big.replay", size: MAX_BYTES + 1 })).toBe("too_large");
    expect(checkFile({ name: "max.replay", size: MAX_BYTES })).toBeNull();
  });

  it("finds the replay class only where it is whole", () => {
    expect(looksLikeReplay(new TextEncoder().encode("....TAGame.Replay_Soccar_TA"))).toBe(true);
    expect(looksLikeReplay(new TextEncoder().encode("....TAGame.Replay"))).toBe(false);
    expect(looksLikeReplay(new Uint8Array())).toBe(false);
  });

  it("looks for the class in the first bytes only", async () => {
    const late = new Uint8Array(4096);
    late.set(new TextEncoder().encode("TAGame.Replay_Soccar_TA"), 1000);
    expect(await precheck(new File([late], "late.replay"))).toBe("not_a_replay");
  });
});

describe("a batch", () => {
  it(`keeps ${MAX_FILES} files and counts the others`, () => {
    const files = Array.from({ length: MAX_FILES + 3 }, (_, index) => index);
    const { kept, left } = splitBatch(files);
    expect(kept).toHaveLength(MAX_FILES);
    expect(kept[0]).toBe(0);
    expect(left).toBe(3);
  });

  it("at the limit, leaves nothing out", () => {
    expect(splitBatch(Array.from({ length: MAX_FILES })).left).toBe(0);
  });
});

describe("the hash", () => {
  it("is the file's SHA-256", async () => {
    expect(await sha256Hex(new Blob(["abc"]))).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });
});
