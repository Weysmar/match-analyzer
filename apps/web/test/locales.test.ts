import { describe, expect, it } from "vitest";
import { pickLocale } from "../src/i18n/locales";

describe("the site's language", () => {
  it.each([
    [undefined, null, "fr"],
    [undefined, "", "fr"],
    [undefined, "en-US,en;q=0.9", "en"],
    [undefined, "fr-FR,fr;q=0.9,en;q=0.8", "fr"],
    [undefined, "de-DE,de;q=0.9,en;q=0.8", "en"],
    [undefined, "de-DE,es;q=0.9", "fr"],
    [undefined, "en;q=0.2,fr;q=0.8", "fr"],
    [undefined, "en;q=0", "fr"],
    ["en", "fr-FR", "en"],
    ["fr", "en-US", "fr"],
    ["de", "en-US", "en"],
  ])("cookie %s and Accept-Language %s give %s", (cookie, header, expected) => {
    expect(pickLocale(cookie, header)).toBe(expected);
  });
});
