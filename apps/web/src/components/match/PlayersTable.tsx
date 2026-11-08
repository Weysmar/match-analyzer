import { getTranslations } from "next-intl/server";
import type { Schemas } from "@/lib/api/client";
import { byTeam } from "@/lib/matches/describe";

const STATS = ["score", "goals", "assists", "saves", "shots"] as const;

/** The scoreboard, by name only (section 11 of CLAUDE.md): no platform id ever reaches the site. */
export async function PlayersTable({ players }: { players: Schemas["Player"][] }) {
  const t = await getTranslations("match");
  const teams = byTeam(players);
  return (
    <section aria-labelledby="players-title" className="flex flex-col gap-3">
      <h2 id="players-title" className="text-lg font-semibold">
        {t("players.title")}
      </h2>
      <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
        <table className="w-full min-w-md text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-400">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("players.name")}
              </th>
              {STATS.map((stat) => (
                <th key={stat} scope="col" className="px-3 py-2 text-right font-medium">
                  {t(`players.${stat}`)}
                </th>
              ))}
            </tr>
          </thead>
          {teams.map((team, index) => (
            <tbody
              // biome-ignore lint/suspicious/noArrayIndexKey: two fixed teams, blue then orange.
              key={index}
              className="divide-y divide-slate-100 border-t border-slate-200 dark:divide-slate-900 dark:border-slate-800"
            >
              <tr>
                <th
                  scope="rowgroup"
                  colSpan={STATS.length + 1}
                  className={`px-3 py-1.5 text-left text-xs font-semibold ${index === 0 ? "text-sky-700 dark:text-sky-300" : "text-orange-700 dark:text-orange-300"}`}
                >
                  {index === 0 ? t("blue") : t("orange")}
                </th>
              </tr>
              {team.map((player) => (
                <tr
                  key={player.match_player_id}
                  className={player.is_me ? "bg-slate-100 dark:bg-slate-800" : undefined}
                >
                  <th scope="row" className="px-3 py-2 text-left font-medium">
                    {player.name}
                    {player.is_me ? (
                      <span className="ml-2 text-xs font-normal text-slate-500">
                        ({t("identity.you")})
                      </span>
                    ) : null}
                    {player.is_bot ? (
                      <span className="ml-2 text-xs font-normal text-slate-500">
                        ({t("players.bot")})
                      </span>
                    ) : null}
                  </th>
                  {STATS.map((stat) => (
                    <td key={stat} className="px-3 py-2 text-right tabular-nums">
                      {player[stat] ?? "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </section>
  );
}
