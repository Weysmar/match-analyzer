import { describe, expect, it } from "vitest";
import { causes, untaggedShare } from "../../src/lib/stats/conceded";

describe("the causes of my goals conceded", () => {
  it("give each tag its share of the goals, worked out by hand", () => {
    // 20 goals: 7 after a double commit (35 %), 5 with the last defender far (25 %), 5 kickoff
    // goals (25 %), 6 with no cause found (30 %). Shares overlap: a goal may carry several tags.
    const conceded = {
      goals: 20,
      untagged: 6,
      tags: { double_commit: 7, last_back_far: 5, kickoff_goal: 5 },
    };
    expect(causes(conceded)).toEqual([
      { tag: "double_commit", goals: 7, share: 35 },
      { tag: "last_back_far", goals: 5, share: 25 },
      { tag: "kickoff_goal", goals: 5, share: 25 },
    ]);
    expect(untaggedShare(conceded)).toBe(30);
  });

  it("keep the cards' order between equal counts, and leave unknown tags out", () => {
    const conceded = {
      goals: 4,
      untagged: 0,
      tags: { own_touch_last: 2, overcommit: 2, mystery: 3 },
    };
    expect(causes(conceded).map((cause) => cause.tag)).toEqual(["overcommit", "own_touch_last"]);
  });

  it("are empty without goals conceded", () => {
    const conceded = { goals: 0, untagged: 0, tags: {} };
    expect(causes(conceded)).toEqual([]);
    expect(untaggedShare(conceded)).toBe(0);
  });
});
