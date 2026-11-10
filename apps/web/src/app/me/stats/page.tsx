import type { Metadata } from "next";
import Link from "next/link";
import { getFormatter, getTranslations } from "next-intl/server";
import { SignInPrompt } from "@/components/account/SignInPrompt";
import { HowItWorks } from "@/components/match/HowItWorks";
import { HistoryChart } from "@/components/stats/HistoryChart";
import { ApiError, type Me, type Schemas } from "@/lib/api/client";
import { serverGet } from "@/lib/api/server";
import { GOAL_TAGS } from "@/lib/matches/conceded";
import { GROUPS, METRICS, show } from "@/lib/matches/metrics";
import { causes, untaggedShare } from "@/lib/stats/conceded";
import { LAST_CHOICES, readQuery, type StatsQuery, statsHref } from "@/lib/stats/query";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("stats");
  return { title: t("title") };
}

const NOTHING: Schemas["Stats"] = {
  matches_count: 0,
  verified_count: 0,
  averages: {},
  conceded: { goals: 0, untagged: 0, tags: {} },
};

async function load(query: StatsQuery) {
  try {
    const [stats, history, me] = await Promise.all([
      serverGet("/api/v1/stats/me", { query: { last: query.last, scope: query.scope } }),
      serverGet("/api/v1/stats/me/history", {
        query: { metric_id: query.metric, last: query.last, scope: query.scope },
      }),
      serverGet("/api/v1/me"),
    ]);
    return { stats, history: history.points, me };
  } catch (error) {
    // No session yet: no match, nothing to average.
    if (error instanceof ApiError && error.status === 401) {
      const me: Me | null = await serverGet("/api/v1/me").catch(() => null);
      return { stats: NOTHING, history: [], me };
    }
    throw error;
  }
}

export default async function StatsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = readQuery(await searchParams);
  const { stats, history, me } = await load(query);
  const t = await getTranslations();
  const format = await getFormatter();
  const chosen = METRICS.find((metric) => metric.id === query.metric) ?? METRICS[0];
  const pill =
    "rounded-md px-3 py-1.5 text-slate-600 hover:bg-slate-100 aria-[current=page]:bg-slate-900 aria-[current=page]:text-white dark:text-slate-300 dark:hover:bg-slate-800 dark:aria-[current=page]:bg-slate-100 dark:aria-[current=page]:text-slate-900";

  function value(id: string, unit: (typeof METRICS)[number]["unit"]) {
    const shown = show(stats.averages[id], unit);
    if (!shown) return t("units.none");
    return t(`units.${shown.unit}`, {
      value: format.number(shown.value, { maximumFractionDigits: shown.digits }),
    });
  }

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("stats.title")}</h1>
        <div className="flex flex-wrap gap-x-6 gap-y-3 text-sm">
          <nav aria-label={t("stats.lastLabel")} className="flex items-center gap-1">
            {LAST_CHOICES.map((last) => (
              <Link
                key={last}
                href={statsHref(query, { last })}
                aria-current={last === query.last ? "page" : undefined}
                className={pill}
              >
                {t("stats.last", { count: last })}
              </Link>
            ))}
          </nav>
          <nav aria-label={t("matches.filter.label")} className="flex items-center gap-1">
            {(["all", "verified"] as const).map((scope) => (
              <Link
                key={scope}
                href={statsHref(query, { scope })}
                aria-current={scope === query.scope ? "page" : undefined}
                className={pill}
              >
                {t(`matches.filter.${scope}`)}
              </Link>
            ))}
          </nav>
        </div>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          {t("stats.counted", { count: stats.matches_count, verified: stats.verified_count })}
        </p>
      </header>

      {stats.matches_count === 0 ? (
        <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed border-slate-300 p-6 dark:border-slate-700">
          <p className="text-slate-600 dark:text-slate-300">
            {query.scope === "verified" ? t("stats.emptyVerified") : t("stats.empty")}
          </p>
          <Link href="/matches" className="font-medium underline">
            {t("stats.toMatches")}
          </Link>
        </div>
      ) : (
        <>
          <section aria-labelledby="history-title" className="flex flex-col gap-3">
            <h2 id="history-title" className="text-lg font-semibold">
              {t(`metrics.${chosen?.id}`)}
            </h2>
            {chosen ? (
              <HistoryChart points={history} unit={chosen.unit} label={t(`metrics.${chosen.id}`)} />
            ) : null}
          </section>

          <section aria-labelledby="averages-title" className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
              <h2 id="averages-title" className="text-lg font-semibold">
                {t("stats.averages")}
              </h2>
              <p className="text-sm text-slate-600 dark:text-slate-400">{t("stats.pick")}</p>
            </div>
            <div className="grid gap-6 sm:grid-cols-2">
              {GROUPS.map((group) => (
                <div key={group} className="flex flex-col gap-2">
                  <h3 className="text-sm font-semibold text-slate-500">
                    {t(`match.metrics.groups.${group}`)}
                  </h3>
                  <ul className="flex flex-col divide-y divide-slate-100 rounded-lg border border-slate-200 dark:divide-slate-900 dark:border-slate-800">
                    {METRICS.filter((metric) => metric.group === group).map((metric) => (
                      <li key={metric.id}>
                        <Link
                          href={statsHref(query, { metric: metric.id })}
                          aria-current={metric.id === query.metric ? "true" : undefined}
                          className="flex items-baseline justify-between gap-4 px-3 py-2 text-sm hover:bg-slate-50 aria-[current=true]:bg-slate-100 dark:hover:bg-slate-900 dark:aria-[current=true]:bg-slate-800"
                        >
                          <span>{t(`metrics.${metric.id}`)}</span>
                          <span className="whitespace-nowrap font-medium tabular-nums">
                            {value(metric.id, metric.unit)}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>

          <section aria-labelledby="conceded-title" className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <h2 id="conceded-title" className="text-lg font-semibold">
                {t("stats.conceded.title")}
              </h2>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {t("stats.conceded.counted", { count: stats.conceded.goals })}
              </p>
            </div>
            {stats.conceded.goals === 0 ? (
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {t("stats.conceded.none")}
              </p>
            ) : (
              <>
                <ul className="flex flex-col gap-2 text-sm">
                  {[
                    ...causes(stats.conceded).map((cause) => ({
                      key: cause.tag,
                      label: t(`match.conceded.tags.${cause.tag}`),
                      share: cause.share,
                      goals: cause.goals,
                    })),
                    ...(stats.conceded.untagged > 0
                      ? [
                          {
                            key: "untagged",
                            label: t("match.conceded.noTag"),
                            share: untaggedShare(stats.conceded),
                            goals: stats.conceded.untagged,
                          },
                        ]
                      : []),
                  ].map((row) => (
                    <li key={row.key} className="flex flex-col gap-1">
                      <span className="flex items-baseline justify-between gap-4">
                        <span>{row.label}</span>
                        <span className="whitespace-nowrap font-medium tabular-nums">
                          {t("stats.conceded.share", {
                            share: format.number(row.share / 100, { style: "percent" }),
                            count: row.goals,
                          })}
                        </span>
                      </span>
                      {/* SVG attributes, not inline styles: the security policy refuses those. */}
                      <svg aria-hidden="true" className="h-1.5 w-full overflow-hidden rounded-full">
                        <rect
                          width="100%"
                          height="100%"
                          className="fill-slate-200 dark:fill-slate-800"
                        />
                        <rect
                          width={`${row.share}%`}
                          height="100%"
                          className={row.key === "untagged" ? "fill-slate-400" : "fill-rose-500"}
                        />
                      </svg>
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-slate-600 dark:text-slate-400">
                  {t("stats.conceded.overlap")}
                </p>
              </>
            )}
            <HowItWorks
              summary={t("definitions.show")}
              items={GOAL_TAGS.map((tag) => ({
                term: t(`match.conceded.tags.${tag}`),
                definition: t(`definitions.tags.${tag}`),
              }))}
            />
          </section>
        </>
      )}

      {me && me.kind !== "user" && stats.matches_count > 0 ? (
        <SignInPrompt epic={me.features.epic_login} returnTo="/me/stats" />
      ) : null}
    </div>
  );
}
