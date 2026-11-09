import { getFormatter, getTranslations } from "next-intl/server";
import type { Schemas } from "@/lib/api/client";
import { possessionSplit } from "@/lib/matches/metrics";

/**
 * Who had the ball (T11.5): each team's share of live play, and the loose ball. Nothing before the
 * analysis, nor for a match parsed before touches were detected. The bar of T16.1 comes later.
 */
export async function TeamPossession({
  teamMetrics,
}: {
  teamMetrics: Schemas["MatchSheet"]["team_metrics"];
}) {
  const split = possessionSplit(teamMetrics);
  if (!split) return null;
  const t = await getTranslations("match.possession");
  const format = await getFormatter();
  const percent = (value: number) => format.number(value / 100, { style: "percent" });

  return (
    <section aria-labelledby="possession-title" className="flex flex-col gap-2">
      <h2 id="possession-title" className="text-lg font-semibold">
        {t("title")}
      </h2>
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm tabular-nums">
        <span className="text-sky-700 dark:text-sky-300">
          {t("blue", { value: percent(split.blue) })}
        </span>
        <span className="text-orange-700 dark:text-orange-300">
          {t("orange", { value: percent(split.orange) })}
        </span>
        <span className="text-slate-600 dark:text-slate-400">
          {t("loose", { value: percent(split.loose) })}
        </span>
      </p>
      <p className="text-xs text-slate-600 dark:text-slate-400">{t("how")}</p>
    </section>
  );
}
