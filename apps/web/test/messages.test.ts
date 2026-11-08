import { describe, expect, it } from "vitest";
import en from "../messages/en.json";
import fr from "../messages/fr.json";
import { PHASES, REASONS } from "../src/lib/upload/state";

/** Texts, nested in objects and, for the legal pages, in lists. */
type Messages = object;

function keys(messages: Messages, prefix = ""): string[] {
  return Object.entries(messages).flatMap(([key, value]: [string, unknown]) =>
    typeof value === "string" ? [`${prefix}${key}`] : keys(value as Messages, `${prefix}${key}.`),
  );
}

function values(messages: Messages): string[] {
  return Object.values(messages).flatMap((value: unknown) =>
    typeof value === "string" ? [value] : values(value as Messages),
  );
}

function placeholders(text: string): string[] {
  // `{name}` or `{name, plural, ...}`: the words inside a plural's branches are text, not names.
  return [...new Set([...text.matchAll(/\{(\w+)[,}]/g)].map((match) => match[1] ?? ""))].sort();
}

describe("messages", () => {
  it("say the same things in French and in English", () => {
    expect(keys(en).sort()).toEqual(keys(fr).sort());
  });

  it("leave no text empty", () => {
    for (const text of [...values(fr), ...values(en)]) expect(text.trim()).not.toBe("");
  });

  it("use the same placeholders in both languages", () => {
    const english = new Map(keys(en).map((key, index) => [key, values(en)[index] ?? ""]));
    keys(fr).forEach((key, index) => {
      expect(placeholders(values(fr)[index] ?? ""), key).toEqual(
        placeholders(english.get(key) ?? ""),
      );
    });
  });

  it("explain every phase and every reason of an upload", () => {
    for (const messages of [fr, en]) {
      for (const phase of PHASES) expect(messages.upload.phases).toHaveProperty(phase);
      for (const reason of REASONS) expect(messages.upload.reasons).toHaveProperty(reason);
    }
  });

  it("never name the game's publisher or the game in the product's name", () => {
    for (const name of [fr.app.name, en.app.name]) {
      expect(name.toLowerCase()).not.toMatch(/rocket league|psyonix|epic games/);
    }
  });
});
