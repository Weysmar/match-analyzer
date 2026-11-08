/** The site's languages (section 8.1 of CLAUDE.md). French first: the first players are French. */
export const LOCALES = ["fr", "en"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "fr";
/** Set by the language switch, for a year. */
export const LOCALE_COOKIE = "locale";

function isLocale(value: string | undefined): value is Locale {
  return (LOCALES as readonly string[]).includes(value ?? "");
}

/**
 * The language to answer in: the one chosen on the site, else the browser's first known one in its
 * order of preference, else French.
 */
export function pickLocale(cookie: string | undefined, acceptLanguage: string | null): Locale {
  if (isLocale(cookie)) return cookie;
  const wanted = (acceptLanguage ?? "")
    .split(",")
    .map((part) => {
      const [tag = "", ...parameters] = part.trim().split(";");
      const quality = parameters.find((parameter) => parameter.trim().startsWith("q="));
      return {
        language: tag.split("-")[0]?.toLowerCase(),
        q: quality ? Number(quality.split("=")[1]) : 1,
      };
    })
    .filter(({ q }) => Number.isFinite(q) && q > 0)
    .sort((a, b) => b.q - a.q);
  return wanted.map(({ language }) => language).find(isLocale) ?? DEFAULT_LOCALE;
}
