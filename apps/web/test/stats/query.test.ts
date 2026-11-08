import { describe, expect, it } from "vitest";
import { signInHref } from "../../src/components/account/SignInOptions";
import { DEFAULTS, readQuery, statsHref } from "../../src/lib/stats/query";

describe("the stats page's address", () => {
  it("gives the defaults when empty", () => {
    expect(readQuery({})).toEqual(DEFAULTS);
  });

  it("reads known choices", () => {
    expect(readQuery({ last: "50", scope: "verified", metric: "move.speed_avg" })).toEqual({
      last: 50,
      scope: "verified",
      metric: "move.speed_avg",
    });
  });

  it("falls back on anything unknown", () => {
    expect(readQuery({ last: "1000", scope: "mine", metric: "nope" })).toEqual(DEFAULTS);
    expect(readQuery({ last: ["10", "20"] }).last).toBe(10);
  });

  it("writes only what differs from the defaults", () => {
    expect(statsHref(DEFAULTS, {})).toBe("/me/stats");
    expect(statsHref(DEFAULTS, { scope: "verified", metric: "pos.pct_last_back" })).toBe(
      "/me/stats?scope=verified&metric=pos.pct_last_back",
    );
  });
});

describe("a sign-in", () => {
  it("starts at the API through the site, back to a path of the site", () => {
    expect(signInHref("steam", "/matches/abc")).toBe(
      "/api/v1/auth/steam?return_to=%2Fmatches%2Fabc",
    );
  });
});
