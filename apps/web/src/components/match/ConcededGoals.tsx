import Link from "next/link";
import { getFormatter, getTranslations } from "next-intl/server";
import type { Schemas } from "@/lib/api/client";
import { type GoalCard, goalCards } from "@/lib/matches/conceded";
import { formatClock } from "@/lib/matches/timeline";
import { viewLink } from "@/lib/view2d/links";

function teamText(team: number | null): string {
  if (team === 0) return "text-sky-700 dark:text-sky-300";
  if (team === 1) return "text-orange-700 dark:text-orange-300";
  return "text-slate-600 dark:text-slate-400";
}

/**
 * The goals conceded (T16.2): a card per goal, with the usual causes found in the play before it
 * (its tags), then its facts, shown without judgment, and a link to watch that play again in the
 * 2D view. Nothing before the analysis.
 */
export async function ConcededGoals({
  sheet,
  viewable,
}: {
  sheet: Schemas["MatchSheet"];
  viewable: boolean;
}) {
  const cards = goalCards(sheet);
  if (cards.length === 0) return null;
  const t = await getTranslations("match.conceded");
  const tt = await getTranslations("match.timeline");
  const ta = await getTranslations("match.analysis");
  const format = await getFormatter();
  const myTeam = sheet.players.find((player) => player.is_me)?.team ?? null;
  const teamName = (team: number | null) =>
    team === 0 ? ta("teams.blue") : team === 1 ? ta("teams.orange") : null;
  const whole = (value: number) => format.number(value, { maximumFractionDigits: 0 });
  const seconds = (value: number) => format.number(value, { maximumFractionDigits: 1 });

  function clockOf(card: GoalCard): string | null {
    if (!card.clock) return null;
    return card.clock.overtime
      ? tt("intoOvertime", { clock: formatClock(card.clock.clockS) })
      : tt("remaining", { clock: formatClock(card.clock.clockS) });
  }

  function lostBallText(card: GoalCard): string | null {
    const lost = card.lostBall;
    if (!lost) return null;
    const when =
      lost.beforeGoalS === null
        ? lost.name
          ? t("lostBallBy", { name: lost.name })
          : t("lostBall")
        : lost.name
          ? t("lostBallByBefore", { name: lost.name, seconds: seconds(lost.beforeGoalS) })
          : t("lostBallBefore", { seconds: seconds(lost.beforeGoalS) });
    const where = lost.ownHalf === null ? null : lost.ownHalf ? t("ownHalf") : t("otherHalf");
    return where ? `${when}, ${where}` : when;
  }

  return (
    <section aria-labelledby="conceded-title" className="flex flex-col gap-3">
      <h2 id="conceded-title" className="text-lg font-semibold">
        {t("title")}
      </h2>
      <p className="text-xs text-slate-600 dark:text-slate-400">{t("how")}</p>
      <ol className="flex flex-col gap-2">
        {cards.map((card) => {
          const clock = clockOf(card);
          const conceding = teamName(card.team);
          const lost = lostBallText(card);
          return (
            <li key={card.id}>
              <details className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
                <summary className="cursor-pointer">
                  <span className="inline-flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    {card.score ? (
                      <span className="font-medium tabular-nums">
                        {tt("score", { blue: card.score.blue, orange: card.score.orange })}
                      </span>
                    ) : null}
                    {conceding ? (
                      <span className={`text-sm ${teamText(card.team)}`}>
                        {t("concededBy", { team: conceding })}
                        {card.team === myTeam ? ` · ${t("yourTeam")}` : null}
                      </span>
                    ) : null}
                    {clock ? (
                      <span className="text-xs text-slate-500 dark:text-slate-400">{clock}</span>
                    ) : null}
                  </span>
                  {/* A summary holds phrasing content only: the tags are spans, read in a row. */}
                  {card.tags.length === 0 ? (
                    <span className="mt-1.5 block text-xs text-slate-500 dark:text-slate-400">
                      {t("noTag")}
                    </span>
                  ) : (
                    <span className="mt-1.5 flex flex-wrap gap-1.5">
                      <span className="sr-only">{t("tagsLabel")} </span>
                      {card.tags.map((tag, index) => (
                        <span
                          key={tag}
                          className="rounded-full bg-slate-100 px-2 py-0.5 text-xs dark:bg-slate-800"
                        >
                          {t(`tags.${tag}`)}
                          {index < card.tags.length - 1 ? <span className="sr-only">,</span> : null}
                        </span>
                      ))}
                    </span>
                  )}
                </summary>
                <div className="mt-3 flex flex-col gap-2 text-sm">
                  <ul className="flex flex-col gap-1">
                    {card.scorerName ? <li>{t("scorer", { name: card.scorerName })}</li> : null}
                    {card.lastTouch ? (
                      <li>
                        {t("lastTouch", { name: card.lastTouch.name })}
                        {card.lastTouch.team === card.team ? ` (${t("ownTeam")})` : null}
                      </li>
                    ) : null}
                    {lost ? <li>{lost}</li> : null}
                    {card.lostBall && card.lostBall.roles.length > 0 ? (
                      <li>
                        {t("roles", {
                          roles: card.lostBall.roles
                            .map((entry) =>
                              t("roleOf", { name: entry.name, role: t(`role.${entry.role}`) }),
                            )
                            .join(", "),
                        })}
                      </li>
                    ) : null}
                  </ul>
                  {card.defenders.length > 0 ? (
                    <div className="flex flex-col gap-1">
                      <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
                        {t("atShot")}
                      </h3>
                      <ul className="flex flex-col gap-1">
                        {card.defenders.map((defender, index) => (
                          // biome-ignore lint/suspicious/noArrayIndexKey: defenders keep their order.
                          <li key={index}>
                            {defender.demolished || defender.distanceM === null
                              ? t("defenderAway", { name: defender.name })
                              : t("defender", {
                                  name: defender.name,
                                  meters: whole(defender.distanceM),
                                  boost: whole(defender.boost ?? 0),
                                })}
                            {defender.lastBack ? ` · ${t("lastBack")}` : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {viewable && card.windowStartS !== null && card.playS !== null ? (
                    <Link
                      href={viewLink(card.windowStartS)}
                      className="text-xs font-medium text-sky-700 underline dark:text-sky-300"
                    >
                      {t("replay", { seconds: seconds(card.playS - card.windowStartS) })}
                      <span className="sr-only">
                        {" "}
                        {card.score
                          ? t("replayGoal", { blue: card.score.blue, orange: card.score.orange })
                          : t("replayThisGoal")}
                      </span>
                    </Link>
                  ) : null}
                </div>
              </details>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
