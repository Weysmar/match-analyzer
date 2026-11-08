import { getTranslations } from "next-intl/server";
import type { Schemas } from "@/lib/api/client";
import { formatClock, placeGoals } from "@/lib/matches/timeline";

/** The goals along the match (T8.10), then the same goals as a list for reading and screen readers. */
export async function GoalTimeline({
  goals,
  match,
}: {
  goals: Schemas["Goal"][];
  match: Schemas["MatchInfo"];
}) {
  const t = await getTranslations("match.timeline");
  const timeline = placeGoals(goals, match);

  return (
    <section aria-labelledby="goals-title" className="flex flex-col gap-3">
      <h2 id="goals-title" className="text-lg font-semibold">
        {t("title")}
      </h2>
      {timeline.goals.length === 0 ? (
        <p className="text-sm text-slate-600 dark:text-slate-400">{t("empty")}</p>
      ) : (
        <>
          {/* SVG attributes, not inline styles: the security policy refuses those (A59). */}
          <div className="px-2">
            <svg aria-hidden="true" className="h-10 w-full overflow-visible">
              <rect
                x="0"
                y="18"
                width="100%"
                height="4"
                rx="2"
                className="fill-slate-200 dark:fill-slate-800"
              />
              {timeline.overtimeLeft !== null ? (
                <rect
                  x={`${timeline.overtimeLeft}%`}
                  y="18"
                  width={`${100 - timeline.overtimeLeft}%`}
                  height="4"
                  className="fill-amber-300 dark:fill-amber-700"
                />
              ) : null}
              {timeline.goals.map((goal, index) => (
                <circle
                  // biome-ignore lint/suspicious/noArrayIndexKey: goals keep their order.
                  key={index}
                  cx={`${goal.left}%`}
                  cy="20"
                  r="7"
                  strokeWidth="2"
                  className={`stroke-white dark:stroke-slate-950 ${goal.team === 0 ? "fill-sky-600" : goal.team === 1 ? "fill-orange-500" : "fill-slate-400"}`}
                />
              ))}
            </svg>
          </div>
          <ol aria-label={t("label")} className="flex flex-col gap-1 text-sm">
            {timeline.goals.map((goal, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: goals keep their order.
              <li key={index} className="flex flex-wrap items-baseline gap-x-3">
                <span className="w-16 shrink-0 tabular-nums font-medium">
                  {t("score", { blue: goal.blue, orange: goal.orange })}
                </span>
                <span
                  className={
                    goal.team === 0
                      ? "text-sky-700 dark:text-sky-300"
                      : "text-orange-700 dark:text-orange-300"
                  }
                >
                  {goal.playerName ?? t("unknownScorer")}
                </span>
                {goal.clockS !== null ? (
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {goal.overtime
                      ? t("intoOvertime", { clock: formatClock(goal.clockS) })
                      : t("remaining", { clock: formatClock(goal.clockS) })}
                  </span>
                ) : null}
              </li>
            ))}
          </ol>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {timeline.overtimeLeft !== null ? `${t("overtime")} · ` : null}
            {timeline.onClock ? t("approximate") : t("noClock")}
          </p>
        </>
      )}
    </section>
  );
}
