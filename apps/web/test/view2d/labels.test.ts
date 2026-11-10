import { mkdtemp, readdir, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { decode } from "../../src/lib/view2d/document";
import {
  fileNameOf,
  labelFile,
  labelQueue,
  parseLabelFile,
  type Verdict,
} from "../../src/lib/view2d/labels";
import { rawView } from "./fixture";

const MATCH = "731bfcac-3c1f-5aa8-9259-226a1098ea5c";
const view = decode(rawView());

describe("the queue of situations", () => {
  it("holds every situation, named by its replay time, with its clock", () => {
    const queue = labelQueue(view, MATCH);
    expect(queue.map((item) => item.timeS).sort()).toEqual([11, 11.1, 12.5, 13.2]);
    expect(new Set(queue.map((item) => item.detector))).toEqual(
      new Set(["turnover", "kickoff", "fifty_fifty"]),
    );
    const first = queue.find((item) => item.timeS === 12.5);
    expect(first).toMatchObject({ detector: "turnover", team: 1, players: [42, 41], clockS: 1.5 });
  });

  it("is shuffled, the same way on every visit", () => {
    const many = decode({
      ...rawView(),
      situations: Array.from({ length: 12 }, (_, index) => ({
        kind: "turnover",
        time_s: 10 + index / 4,
        team: 0,
        players: [41],
      })),
    });
    const order = labelQueue(many, MATCH).map((item) => item.timeS);
    expect(labelQueue(many, MATCH).map((item) => item.timeS)).toEqual(order);
    expect(order).not.toEqual([...order].sort((a, b) => a - b));
  });

  it("is empty without detections", () => {
    expect(labelQueue(decode({ ...rawView(), situations: null }), MATCH)).toEqual([]);
  });
});

describe("the label file", () => {
  const queue = labelQueue(view, MATCH);
  const turnover = queue.findIndex((item) => item.detector === "turnover");
  const kickoff = queue.findIndex((item) => item.detector === "kickoff");
  const verdicts = new Map<number, Verdict>([
    [turnover, "true"],
    [kickoff, "false"],
  ]);

  it("keeps only what was judged, one detector at a time, without any name", () => {
    const file = labelFile(MATCH, "turnover", queue, verdicts, new Date("2026-11-10T20:00:00Z"));
    expect(file).toEqual({
      version: 1,
      match_id: MATCH,
      detector: "turnover",
      labeled_at: "2026-11-10T20:00:00.000Z",
      labels: [
        { time_s: queue[turnover]?.timeS, clock_s: queue[turnover]?.clockS, verdict: "true" },
      ],
    });
    expect(labelFile(MATCH, "kickoff", queue, verdicts, new Date()).labels).toEqual([
      { time_s: queue[kickoff]?.timeS, clock_s: queue[kickoff]?.clockS, verdict: "false" },
    ]);
    expect(parseLabelFile(file)).toEqual(file);
    expect(fileNameOf(file)).toBe(`${MATCH}-turnover.json`);
  });

  it.each([
    ["another detector", { detector: "../../etc" }],
    ["a match that is no id", { match_id: "../x" }],
    ["an unknown verdict", { labels: [{ time_s: 1, clock_s: 1, verdict: "maybe" }] }],
    ["an extra field", { name: "someone" }],
    ["another version", { version: 2 }],
  ])("refuses %s", (_, change) => {
    const file = labelFile(MATCH, "turnover", queue, verdicts, new Date());
    expect(parseLabelFile({ ...file, ...change })).toBeNull();
  });
});

describe("the export", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  const request = (body: unknown, origin = "http://localhost:3000") =>
    new Request("http://localhost:3000/dev/labels", {
      method: "POST",
      headers: { origin, "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  const file = labelFile(
    MATCH,
    "turnover",
    labelQueue(view, MATCH),
    new Map([[0, "false"]]),
    new Date(),
  );

  it("does not exist outside development", async () => {
    vi.stubEnv("NODE_ENV", "production");
    const { POST } = await import("../../src/app/dev/labels/route");
    expect((await POST(request(file))).status).toBe(404);
  });

  it("writes the file under its own name in development", async () => {
    const folder = await mkdtemp(path.join(tmpdir(), "labels-"));
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("LABELS_DIR", folder);
    const { POST } = await import("../../src/app/dev/labels/route");
    const response = await POST(request(file));
    expect(response.status).toBe(200);
    expect(await readdir(folder)).toEqual([`${MATCH}-turnover.json`]);
    expect(
      JSON.parse(await readFile(path.join(folder, `${MATCH}-turnover.json`), "utf-8")),
    ).toEqual(file);
  });

  it("refuses another site and a file off its format", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("LABELS_DIR", await mkdtemp(path.join(tmpdir(), "labels-")));
    const { POST } = await import("../../src/app/dev/labels/route");
    expect((await POST(request(file, "http://evil.test"))).status).toBe(403);
    expect((await POST(request({ ...file, version: 2 }))).status).toBe(422);
  });
});
