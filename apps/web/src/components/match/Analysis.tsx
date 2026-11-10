import Link from "next/link";
import { getFormatter, getTranslations } from "next-intl/server";
import { HowItWorks } from "@/components/match/HowItWorks";
import type { Schemas } from "@/lib/api/client";
import {
  duelCounts,
  kickoffCounts,
  type ListedSituation,
  listSituations,
  possessionBar,
} from "@/lib/matches/analysis";
import { kickoffGoals, overcommits, possessionSplit, TEAM_METRICS } from "@/lib/matches/metrics";
import { formatClock } from "@/lib/matches/timeline";
import { situationLink } from "@/lib/view2d/links";

const BAR_COLORS = {
  blue: "fill-sky-600",
  loose: "fill-slate-300 dark:fill-slate-700",
  orange: "fill-orange-500",
} as const;

function teamText(team: number | null): string {
  if (team === 0) return "text-sky-700 dark:text-sky-300";
  if (team === 1) return "text-orange-700 dark:text-orange-300";
  return "text-slate-600 dark:text-slate-400";
}

/**
 * The analysis of the match (T16.1): who had the ball, kickoffs and duels in a sentence each, then
 * the situations the detections found, by kind, each linked to its moment in the 2D view. Nothing
 * before the analysis, nor for a match parsed before touches were detected.
 */
export async function Analysis({
  sheet,
  viewable,
}: {
  sheet: Schemas["MatchSheet"];
  viewable: boolean;
}) {
  const split = possessionSplit(sheet.team_metrics);
  const kickoffs = kickoffCounts(sheet.situations);
  const duels = duelCounts(sheet.situations);
  const groups = listSituations(sheet.situations, sheet.players, sheet.match);
  if (!split && kickoffs.total === 0 && duels.total === 0 && groups.length === 0) return null;

  const t = await getTranslations("match.analysis");
  const tp = await getTranslations("match.possession");
  const tt = await getTranslations("match.timeline");
  const tv = await getTranslations("match.view");
  const td = await getTranslations("definitions");
  const tm = await getTranslations("metrics");
  const format = await getFormatter();
  const percent = (value: number) => format.number(value / 100, { style: "percent" });
  const kickoffGoalCounts = kickoffGoals(sheet.team_metrics);
  const caught = overcommits(sheet.team_metrics);
  const teamName = (team: number | null) =>
    team === 0 ? t("teams.blue") : team === 1 ? t("teams.orange") : null;

  function sentence(situation: ListedSituation): string {
    const [first, second] = situation.names;
    const team = teamName(situation.team);
    switch (situation.kind) {
      case "turnover":
        if (first !== undefined && second !== undefined) {
          return t("item.turnover", { won: first, lost: second });
        }
        return first !== undefined ? t("item.turnoverWinner", { won: first }) : "";
      case "kickoff": {
        const outcome = team ? t("item.kickoffWon", { team }) : t("item.kickoffNeutral");
        return situation.goal ? `${outcome} · ${t("item.kickoffGoal")}` : outcome;
      }
      case "fifty_fifty": {
        const after = team ? t("item.duelAfter", { team }) : t("item.duelLoose");
        return situation.names.length > 0 ? `${situation.names.join(" – ")} · ${after}` : after;
      }
      case "double_commit": {
        const who = situation.names.join(", ");
        return situation.punished ? `${who} · ${t("item.punished")}` : who;
      }
      case "overcommit":
        return t("item.overcommit", {
          team: team ?? "",
          seconds: format.number(situation.durationS ?? 0, { maximumFractionDigits: 1 }),
        });
    }
  }

  return (
    <section aria-labelledby="analysis-title" className="flex flex-col gap-4">
      <h2 id="analysis-title" className="text-lg font-semibold">
        {t("title")}
      </h2>

      {split ? (
        <div className="flex flex-col gap-2">
          <h3 className="font-medium">{tp("title")}</h3>
          {/* SVG attributes, not inline styles: the security policy refuses those (A59). */}
          <svg aria-hidden="true" className="h-4 w-full overflow-hidden rounded-full">
            {possessionBar(split).map((segment) => (
              <rect
                key={segment.part}
                x={`${segment.from}%`}
                y="0"
                width={`${segment.width}%`}
                height="100%"
                className={BAR_COLORS[segment.part]}
              />
            ))}
          </svg>
          <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm tabular-nums">
            <span className="text-sky-700 dark:text-sky-300">
              {tp("blue", { value: percent(split.blue) })}
            </span>
            <span className="text-slate-600 dark:text-slate-400">
              {tp("loose", { value: percent(split.loose) })}
            </span>
            <span className="text-orange-700 dark:text-orange-300">
              {tp("orange", { value: percent(split.orange) })}
            </span>
          </p>
          <p className="text-xs text-slate-600 dark:text-slate-400">{tp("how")}</p>
        </div>
      ) : null}

      {kickoffs.total > 0 || duels.total > 0 || kickoffGoalCounts || caught ? (
        <ul className="flex flex-col gap-1 text-sm">
          {kickoffs.total > 0 ? (
            <li>
              {t("kickoffs", {
                count: kickoffs.total,
                blue: kickoffs.blue,
                orange: kickoffs.orange,
                neutral: kickoffs.none,
              })}
            </li>
          ) : null}
          {kickoffGoalCounts ? (
            <li>
              {tp("kickoffGoals", {
                blue: kickoffGoalCounts.blue,
                orange: kickoffGoalCounts.orange,
              })}
            </li>
          ) : null}
          {duels.total > 0 ? (
            <li>
              {t("duels", {
                count: duels.total,
                blue: duels.blue,
                orange: duels.orange,
                loose: duels.none,
              })}
            </li>
          ) : null}
          {caught ? (
            <li>{tp("overcommits", { blue: caught.blue, orange: caught.orange })}</li>
          ) : null}
        </ul>
      ) : null}

      <HowItWorks
        summary={td("showMetrics")}
        items={TEAM_METRICS.filter(
          (metric) => sheet.team_metrics["0"]?.[metric.id] !== undefined,
        ).map((metric) => ({
          term: tm(`${metric.id}`),
          definition: td(`metrics.${metric.id}`),
        }))}
      />

      {groups.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="font-medium">{t("situations")}</h3>
          {viewable ? (
            <p className="text-xs text-slate-600 dark:text-slate-400">{t("situationsHow")}</p>
          ) : null}
          {groups.map((group) => (
            <details
              key={group.kind}
              className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800"
            >
              <summary className="cursor-pointer text-sm font-medium">
                {tv(`situations.${group.kind}`, { count: group.items.length })}
              </summary>
              <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">
                {td(`situations.${group.kind}`)}
              </p>
              <ol className="mt-2 flex flex-col gap-1.5 text-sm">
                {group.items.map((situation) => {
                  const clock = situation.clock
                    ? situation.clock.overtime
                      ? tt("intoOvertime", { clock: formatClock(situation.clock.clockS) })
                      : tt("remaining", { clock: formatClock(situation.clock.clockS) })
                    : null;
                  return (
                    <li key={situation.id} className="flex flex-wrap items-baseline gap-x-3">
                      {clock ? (
                        <span className="w-28 shrink-0 text-xs tabular-nums text-slate-500 dark:text-slate-400">
                          {clock}
                        </span>
                      ) : null}
                      <span className={teamText(situation.team)}>{sentence(situation)}</span>
                      {viewable && situation.playS !== null ? (
                        <Link
                          href={situationLink(situation.playS)}
                          className="text-xs font-medium text-sky-700 underline dark:text-sky-300"
                        >
                          {tt("replay")}
                          <span className="sr-only">
                            {" "}
                            {t("replaySituation", {
                              kind: t(`kinds.${situation.kind}`),
                              clock: clock ?? "",
                            })}
                          </span>
                        </Link>
                      ) : null}
                    </li>
                  );
                })}
              </ol>
            </details>
          ))}
        </div>
      ) : null}
    </section>
  );
}
