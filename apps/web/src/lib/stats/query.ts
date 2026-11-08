/** The choices of the stats page, read from its address and written back into its links. */
import { METRICS } from "@/lib/matches/metrics";

export const LAST_CHOICES = [10, 20, 50] as const;
export type Last = (typeof LAST_CHOICES)[number];
export type Scope = "all" | "verified";

export interface StatsQuery {
  last: Last;
  scope: Scope;
  metric: string;
}

export const DEFAULTS: StatsQuery = { last: 20, scope: "all", metric: "boost.avg" };

/** Anything unknown falls back to the default: the address is the visitor's to type. */
export function readQuery(search: Record<string, string | string[] | undefined>): StatsQuery {
  const one = (name: string) => {
    const value = search[name];
    return Array.isArray(value) ? value[0] : value;
  };
  const last = Number(one("last"));
  const metric = one("metric");
  return {
    last: (LAST_CHOICES as readonly number[]).includes(last) ? (last as Last) : DEFAULTS.last,
    scope: one("scope") === "verified" ? "verified" : "all",
    metric: METRICS.some((known) => known.id === metric) ? (metric as string) : DEFAULTS.metric,
  };
}

/** The page's address with some choices changed; defaults are left out. */
export function statsHref(current: StatsQuery, change: Partial<StatsQuery>): string {
  const next = { ...current, ...change };
  const query = new URLSearchParams();
  if (next.last !== DEFAULTS.last) query.set("last", String(next.last));
  if (next.scope !== DEFAULTS.scope) query.set("scope", next.scope);
  if (next.metric !== DEFAULTS.metric) query.set("metric", next.metric);
  return query.size > 0 ? `/me/stats?${query}` : "/me/stats";
}
