import { getFormatter, getTranslations } from "next-intl/server";
import { HowItWorks } from "@/components/match/HowItWorks";
import type { Schemas } from "@/lib/api/client";
import { GROUPS, METRICS, show } from "@/lib/matches/metrics";

/**
 * Every V1 metric of every player (T8.9): rows are metrics, columns are players, the viewer first,
 * then their team, then the opponents. Wide tables scroll on their own, never the page.
 */
export async function MetricsTable({
  players,
  metrics,
}: {
  players: Schemas["Player"][];
  metrics: Schemas["MatchSheet"]["metrics"];
}) {
  const t = await getTranslations();
  const format = await getFormatter();
  const me = players.find((player) => player.is_me);
  const columns = players
    .filter((player) => metrics[String(player.match_player_id)] !== undefined)
    .sort(
      (a, b) =>
        Number(b.is_me) - Number(a.is_me) ||
        Number(b.team === me?.team) - Number(a.team === me?.team) ||
        a.team - b.team,
    );

  function cell(value: number | null | undefined, unit: (typeof METRICS)[number]["unit"]) {
    const shown = show(value, unit);
    if (!shown) return t("units.none");
    return t(`units.${shown.unit}`, {
      value: format.number(shown.value, { maximumFractionDigits: shown.digits }),
    });
  }

  return (
    <section aria-labelledby="metrics-title" className="flex flex-col gap-3">
      <h2 id="metrics-title" className="text-lg font-semibold">
        {t("match.metrics.title")}
      </h2>
      {columns.length === 0 ? (
        <p className="text-sm text-slate-600 dark:text-slate-400">{t("match.metrics.none")}</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-400">
              <tr>
                <th
                  scope="col"
                  className="sticky left-0 bg-slate-50 px-3 py-2 text-left font-medium dark:bg-slate-900"
                >
                  {t("match.metrics.metric")}
                </th>
                {columns.map((player) => (
                  <th
                    key={player.match_player_id}
                    scope="col"
                    className={`max-w-28 truncate px-3 py-2 text-right font-medium ${player.team === 0 ? "text-sky-700 dark:text-sky-300" : "text-orange-700 dark:text-orange-300"}`}
                  >
                    {player.is_me ? t("match.identity.you") : player.name}
                  </th>
                ))}
              </tr>
            </thead>
            {GROUPS.map((group) => (
              <tbody
                key={group}
                className="divide-y divide-slate-100 border-t border-slate-200 dark:divide-slate-900 dark:border-slate-800"
              >
                <tr>
                  <th
                    scope="rowgroup"
                    colSpan={columns.length + 1}
                    className="sticky left-0 px-3 py-1.5 text-left text-xs font-semibold text-slate-500"
                  >
                    {t(`match.metrics.groups.${group}`)}
                  </th>
                </tr>
                {METRICS.filter((metric) => metric.group === group).map((metric) => (
                  <tr key={metric.id}>
                    <th
                      scope="row"
                      className="sticky left-0 bg-white px-3 py-2 text-left font-normal dark:bg-slate-950"
                    >
                      {t(`metrics.${metric.id}`)}
                    </th>
                    {columns.map((player) => (
                      <td
                        key={player.match_player_id}
                        className={`whitespace-nowrap px-3 py-2 text-right tabular-nums ${player.is_me ? "font-semibold" : ""}`}
                      >
                        {cell(metrics[String(player.match_player_id)]?.[metric.id], metric.unit)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      )}
      <HowItWorks
        summary={t("definitions.showMetrics")}
        items={METRICS.map((metric) => ({
          term: t(`metrics.${metric.id}`),
          definition: t(`definitions.metrics.${metric.id}`),
        }))}
      />
    </section>
  );
}
