import type { Metadata } from "next";
import Link from "next/link";
import { getFormatter, getTranslations } from "next-intl/server";
import { SignInPrompt } from "@/components/account/SignInPrompt";
import { Analysis } from "@/components/match/Analysis";
import { AutoRefresh } from "@/components/match/AutoRefresh";
import { ConcededGoals } from "@/components/match/ConcededGoals";
import { GoalTimeline } from "@/components/match/GoalTimeline";
import { IdentityPicker } from "@/components/match/IdentityPicker";
import { MetricsTable } from "@/components/match/MetricsTable";
import { PlayersTable } from "@/components/match/PlayersTable";
import { MatchView } from "@/components/view2d/MatchView";
import { serverGet } from "@/lib/api/server";
import { claimable, duration, inProgress, playlistKind, teamSize } from "@/lib/matches/describe";
import { sheet } from "@/lib/matches/sheet";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("match");
  return { title: t("titleNoDate") };
}

export default async function MatchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [data, me] = await Promise.all([sheet(id), serverGet("/api/v1/me").catch(() => null)]);
  const { match } = data;
  const t = await getTranslations("match");
  const tm = await getTranslations("matches");
  const format = await getFormatter();
  const size = teamSize(match.team_size);
  const length = duration(match.game_length_s ?? match.duration_s);
  const candidates = claimable(data.players).map((player) => ({
    id: player.match_player_id,
    name: player.name,
    team: player.team,
  }));

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-3">
        <Link href="/matches" className="text-sm text-slate-600 underline dark:text-slate-400">
          {t("back")}
        </Link>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
          {match.played_at
            ? t("title", {
                date: format.dateTime(new Date(match.played_at), {
                  dateStyle: "long",
                  timeStyle: "short",
                }),
              })
            : t("titleNoDate")}
        </h1>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          {[
            tm(`kinds.${playlistKind(match.playlist)}`),
            size,
            match.map,
            length ? t("duration", { duration: length }) : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
        <p className="flex items-baseline gap-4 text-4xl font-bold tabular-nums">
          <span className="text-sky-700 dark:text-sky-300">
            <span className="sr-only">{t("blue")} </span>
            {match.score.blue ?? "?"}
          </span>
          <span aria-hidden="true" className="text-slate-400">
            –
          </span>
          <span className="text-orange-700 dark:text-orange-300">
            <span className="sr-only">{t("orange")} </span>
            {match.score.orange ?? "?"}
          </span>
        </p>
      </header>

      {inProgress(match.status) ? (
        <p
          role="status"
          className="rounded-lg bg-sky-50 p-4 text-sm text-sky-900 dark:bg-sky-950 dark:text-sky-100"
        >
          {t("inProgress")}
          <AutoRefresh everyMs={3000} />
        </p>
      ) : null}
      {match.status === "header_only" ? (
        <p className="rounded-lg bg-amber-50 p-4 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100">
          {t("partial")}
        </p>
      ) : null}
      {match.status === "failed" ? (
        <p className="rounded-lg bg-red-50 p-4 text-sm text-red-900 dark:bg-red-950 dark:text-red-100">
          {t("failed")}
        </p>
      ) : null}

      <IdentityPicker
        matchId={match.match_id}
        players={candidates}
        meId={data.me.match_player_id}
        verified={data.me.verified}
        open={data.needs_identity}
      />

      {me && me.kind !== "user" && !inProgress(match.status) ? (
        <SignInPrompt epic={me.features.epic_login} returnTo={`/matches/${match.match_id}`} />
      ) : null}

      <PlayersTable players={data.players} />
      <GoalTimeline goals={data.goals} match={match} viewable={match.status === "ready"} />
      {match.status === "ready" ? (
        <MatchView
          matchId={match.match_id}
          players={data.players.map((player) => ({
            id: player.match_player_id,
            name: player.name,
            team: player.team,
            isMe: player.is_me,
          }))}
          gameLengthS={match.game_length_s}
          overtimeFromS={match.overtime_from_s}
        />
      ) : null}
      {process.env.NODE_ENV === "development" && match.status === "ready" ? (
        <Link href={`/matches/${match.match_id}/labels`} className="text-sm underline">
          {t("labels.open")}
        </Link>
      ) : null}
      <Analysis sheet={data} viewable={match.status === "ready"} />
      <ConcededGoals sheet={data} viewable={match.status === "ready"} />
      <MetricsTable players={data.players} metrics={data.metrics} />
    </div>
  );
}
