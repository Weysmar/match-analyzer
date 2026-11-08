import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, fillPath, getJson } from "../src/lib/api/client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("paths", () => {
  it("fill and encode their parameters", () => {
    expect(fillPath("/api/v1/matches/{match_id}", { match_id: "a/b c" })).toBe(
      "/api/v1/matches/a%2Fb%20c",
    );
  });

  it("refuse a missing parameter", () => {
    expect(() => fillPath("/api/v1/matches/{match_id}")).toThrow("match_id");
  });
});

describe("calls", () => {
  it("return the API's JSON", async () => {
    const fetch = vi.fn(async () => Response.json({ kind: "none" }));
    vi.stubGlobal("fetch", fetch);
    const me = await getJson("/api/v1/me", { base: "http://api.test" });
    expect(me.kind).toBe("none");
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/v1/me", expect.any(Object));
  });

  it("turn an error of the API into its code", async () => {
    vi.stubGlobal("fetch", async () =>
      Response.json({ error: { code: "not_signed_in" } }, { status: 401 }),
    );
    await expect(getJson("/api/v1/matches")).rejects.toEqual(new ApiError(401, "not_signed_in"));
  });

  it("call any other failure internal", async () => {
    vi.stubGlobal("fetch", async () => new Response("<html>", { status: 502 }));
    await expect(getJson("/api/v1/matches")).rejects.toEqual(new ApiError(502, "internal"));
  });
});
