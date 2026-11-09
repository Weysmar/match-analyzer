import { describe, expect, it } from "vitest";
import en from "../../messages/en.json";
import fr from "../../messages/fr.json";
import { GROUPS, METRICS, show } from "../../src/lib/matches/metrics";

describe("the catalog of metrics", () => {
  it("holds the 25 metrics, each in a known group", () => {
    expect(METRICS).toHaveLength(25);
    for (const metric of METRICS) expect(GROUPS).toContain(metric.group);
  });

  it("names every metric in French and in English", () => {
    for (const messages of [fr, en]) {
      for (const metric of METRICS) {
        const [group = "", name = ""] = metric.id.split(".");
        const labels = messages.metrics as Record<string, Record<string, string>>;
        expect(labels[group]?.[name], `${metric.id}`).toBeTruthy();
      }
    }
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
