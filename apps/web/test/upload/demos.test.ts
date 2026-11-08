import { describe, expect, it } from "vitest";
import { factsKey, IMPORT_LIMIT, newReplays, remember } from "../../src/lib/upload/demos";

const file = (name: string, lastModified: number, size = 1000) => ({ name, size, lastModified });

describe("new replays of the Demos folder", () => {
  it("are the replays not brought yet, most recent first", () => {
    const known = new Set([factsKey(file("old.replay", 1))]);
    const found = newReplays(
      [file("old.replay", 1), file("b.replay", 3), file("a.replay", 2), file("notes.txt", 9)],
      known,
    );
    expect(found.map((f) => f.name)).toEqual(["b.replay", "a.replay"]);
  });

  it(`are the ${IMPORT_LIMIT} most recent the first time`, () => {
    const files = Array.from({ length: 120 }, (_, index) => file(`${index}.replay`, index));
    const found = newReplays(files, new Set());
    expect(found).toHaveLength(IMPORT_LIMIT);
    expect(found[0]?.name).toBe("119.replay");
  });

  it("include a file saved again under the same name", () => {
    const known = new Set([factsKey(file("x.replay", 1))]);
    expect(newReplays([file("x.replay", 2)], known)).toHaveLength(1);
  });
});

describe("the files already brought", () => {
  it("keep the latest ones beyond the limit", () => {
    const many = Array.from({ length: 5000 }, (_, index) => `k${index}`);
    const kept = remember(many, ["new"]);
    expect(kept).toHaveLength(5000);
    expect(kept.at(-1)).toBe("new");
    expect(kept[0]).toBe("k1");
  });

  it("are never counted twice", () => {
    expect(remember(["a", "b"], ["a"])).toEqual(["b", "a"]);
  });
});
