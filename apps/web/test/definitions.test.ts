import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import en from "../messages/en.json";
import fr from "../messages/fr.json";
import catalog from "../metrics.json";
import openapi from "../openapi.json";
import { GOAL_TAGS } from "../src/lib/matches/conceded";

/** "How it is detected" (T16.3): one sentence for each thing the site measures or detects. */

type Tree = { [key: string]: string | Tree };

function lookup(messages: Tree, path: string): string | undefined {
  let node: string | Tree | undefined = messages;
  for (const part of path.split(".")) {
    if (typeof node !== "object") return undefined;
    node = node[part];
  }
  return typeof node === "string" ? node : undefined;
}

function leaves(tree: Tree, prefix = ""): string[] {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === "string" ? [`${prefix}${key}`] : leaves(value, `${prefix}${key}.`),
  );
}

const LANGUAGES = { fr: fr as unknown as Tree, en: en as unknown as Tree };
const SITUATION_KINDS: string[] = openapi.components.schemas.SituationKind.enum;

describe.each(Object.entries(LANGUAGES))("definitions in %s", (_language, messages) => {
  it("cover every metric of the catalog, player and team alike", () => {
    for (const metric of catalog) {
      expect(lookup(messages, `definitions.metrics.${metric.id}`), metric.id).toBeTruthy();
    }
  });

  it("cover every kind of situation the API can send", () => {
    for (const kind of SITUATION_KINDS) {
      expect(lookup(messages, `definitions.situations.${kind}`), kind).toBeTruthy();
    }
  });

  it("cover every tag of a goal conceded", () => {
    for (const tag of GOAL_TAGS) {
      expect(lookup(messages, `definitions.tags.${tag}`), tag).toBeTruthy();
    }
  });

  it("define nothing that does not exist", () => {
    const definitions = (messages.definitions as Tree) ?? {};
    const metrics = new Set(catalog.map((metric) => metric.id));
    expect(leaves(definitions.metrics as Tree).filter((id) => !metrics.has(id))).toEqual([]);
    expect(Object.keys(definitions.situations as Tree).sort()).toEqual([...SITUATION_KINDS].sort());
    expect(Object.keys(definitions.tags as Tree).sort()).toEqual([...GOAL_TAGS].sort());
  });
});

describe("the tags of a goal conceded", () => {
  it("are the analysis' own, in its order", () => {
    // rl_analysis/conceded.py is the source of the tags; the site cannot import it.
    const source = readFileSync(
      new URL("../../../games/rocket-league/analysis/src/rl_analysis/conceded.py", import.meta.url),
      "utf-8",
    );
    const block = source.match(/^TAGS = \(([\s\S]*?)^\)/m)?.[1] ?? "";
    const tags = [...block.matchAll(/"(\w+)"/g)].map((match) => match[1]);
    expect(tags).toEqual([...GOAL_TAGS]);
  });
});
