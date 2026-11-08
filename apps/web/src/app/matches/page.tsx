import type { Metadata } from "next";
import Link from "next/link";
import { getFormatter, getTranslations } from "next-intl/server";
import { ApiError, type Schemas } from "@/lib/api/client";
import { serverGet } from "@/lib/api/server";
import { inProgress, playlistKind, teamSize } from "@/lib/matches/describe";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("matches");
  return { title: t("title") };
}

type Scope = "all" | "verified";

async function page(scope: Scope, cursor: string | undefined): Promise<Schemas["MatchPage"]> {
  try {
    return await serverGet("/api/v1/matches", { query: { scope, cursor, limit: 25 } });
  } catch (error) {
    // No session yet: nothing uploaded, nothing to list.
    if (error instanceof ApiError && error.status === 401) return { items: [], next_cursor: null };
    throw error;
  }
}

export default async function MatchesPage({
  searchParams,
}: {
  searchParams: Promise<{ scope?: string; cursor?: string }>;
}) {
  const query = await searchParams;
  const scope: Scope = query.scope === "verified" ? "verified" : "all";
  const { items, next_cursor } = await page(scope, query.cursor);
  const t = await getTranslations("matches");
  const format = await getFormatter();

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("title")}</h1>
        <nav aria-label={t("filter.label")} className="flex gap-1 text-sm">
          {(["all", "verified"] as const).map((option) => (
            <Link
              key={option}
              href={option === "all" ? "/matches" : "/matches?scope=verified"}
              aria-current={option === scope ? "page" : undefined}
              className="rounded-md px-3 py-1.5 text-slate-600 hover:bg-slate-100 aria-[current=page]:bg-slate-900 aria-[current=page]:text-white dark:text-slate-300 dark:hover:bg-slate-800 dark:aria-[current=page]:bg-slate-100 dark:aria-[current=page]:text-slate-900"
            >
              {t(`filter.${option}`)}
            </Link>
          ))}
        </nav>
      </header>

      {items.length === 0 ? (
        <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed border-slate-300 p-6 dark:border-slate-700">
          <p className="text-slate-600 dark:text-slate-300">{t("empty")}</p>
          <Link href="/upload" className="font-medium underline">
            {t("emptyCta")}
          </Link>
        </div>
      ) : (
        <ul className="flex flex-col divide-y divide-slate-200 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
          {items.map((match) => {
            const size = teamSize(match.team_size);
            const result = match.won === null ? "unknown" : match.won ? "won" : ("lost" as const);
            return (
              <li key={match.match_id}>
                <Link
                  href={`/matches/${match.match_id}`}
                  className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-900"
                >
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="font-medium">
                      {match.played_at
                        ? format.dateTime(new Date(match.played_at), {
                            dateStyle: "medium",
                            timeStyle: "short",
                          })
                        : t("unknownDate")}
                    </span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {[t(`kinds.${playlistKind(match.playlist)}`), size, match.map]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-3 text-sm">
                    {!match.verified ? (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200">
                        {t("unverified")}
                      </span>
                    ) : null}
                    {match.status !== "ready" ? (
                      <span
                        className={`text-xs ${inProgress(match.status) ? "text-sky-700 dark:text-sky-300" : "text-amber-700 dark:text-amber-300"}`}
                      >
                        {t(`status.${match.status}`)}
                      </span>
                    ) : null}
                    <span className="tabular-nums">
                      <span className="text-sky-700 dark:text-sky-300">
                        {match.score.blue ?? "?"}
                      </span>
                      {" – "}
                      <span className="text-orange-700 dark:text-orange-300">
                        {match.score.orange ?? "?"}
                      </span>
                    </span>
                    <span
                      className={
                        result === "won"
                          ? "font-medium text-emerald-700 dark:text-emerald-300"
                          : result === "lost"
                            ? "font-medium text-red-700 dark:text-red-300"
                            : "text-slate-500"
                      }
                    >
                      {t(`result.${result}`)}
                    </span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      {next_cursor ? (
        <Link
          href={`/matches?${new URLSearchParams({ ...(scope === "verified" ? { scope } : {}), cursor: next_cursor })}`}
          className="self-start font-medium underline"
        >
          {t("more")}
        </Link>
      ) : null}
    </div>
  );
}
