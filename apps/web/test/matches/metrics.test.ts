import { describe, expect, it } from "vitest";
import en from "../../messages/en.json";
import fr from "../../messages/fr.json";
import {
  GROUPS,
  METRICS,
  possessionSplit,
  show,
  TEAM_METRICS,
} from "../../src/lib/matches/metrics";

describe("the catalog of metrics", () => {
  it("holds the 28 player metrics, each in a known group", () => {
    expect(METRICS).toHaveLength(28);
    for (const metric of METRICS) expect(GROUPS).toContain(metric.group);
  });

  it("keeps the team metrics apart", () => {
    expect(TEAM_METRICS.map((metric) => metric.id)).toEqual(["poss.team_pct"]);
    expect(METRICS.map((metric) => metric.id)).not.toContain("poss.team_pct");
  });

  it("names every metric in French and in English", () => {
    for (const messages of [fr, en]) {
      for (const metric of [...METRICS, ...TEAM_METRICS]) {
        const [group = "", name = ""] = metric.id.split(".");
        const labels = messages.metrics as Record<string, Record<string, string>>;
        expect(labels[group]?.[name], `${metric.id}`).toBeTruthy();
      }
    }
  });
});

describe("the possession split", () => {
  it("gives each team its share, and the rest to the loose ball", () => {
    const split = possessionSplit({ "0": { "poss.team_pct": 31.5 }, "1": { "poss.team_pct": 22 } });
    expect(split).toEqual({ blue: 31.5, orange: 22, loose: 46.5 });
  });

  it("is nothing without possession for both teams", () => {
    expect(possessionSplit({})).toBeNull();
    expect(
      possessionSplit({ "0": { "poss.team_pct": null }, "1": { "poss.team_pct": 10 } }),
    ).toBeNull();
  });
});

describe("a value as shown", () => {
  it("keeps a percentage", () => {
    expect(show(42.4, "%")).toEqual({ value: 42.4, unit: "percent", digits: 0 });
  });

  it("turns a speed into km/h: 2300 uu/s is 82.8 km/h", () => {
    expect(show(2300, "uu/s")?.value).toBeCloseTo(82.8);
    expect(show(2300, "uu/s")?.unit).toBe("kmh");
  });

  it("turns a distance into meters", () => {
    expect(show(2500, "uu")).toEqual({ value: 25, unit: "meters", digits: 1 });
  });

  it("keeps a count whole", () => {
    expect(show(3, "count")).toEqual({ value: 3, unit: "count", digits: 0 });
  });

  it.each([null, undefined, Number.NaN])("shows nothing for %s", (value) => {
    expect(show(value, "%")).toBeNull();
  });
});
