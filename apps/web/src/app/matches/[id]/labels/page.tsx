import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { GoalReview } from "@/components/view2d/GoalReview";
import { LabelQueue } from "@/components/view2d/LabelQueue";
import { MatchView } from "@/components/view2d/MatchView";
import { WindowReview } from "@/components/view2d/WindowReview";
import { GOAL_TAGS, type GoalTag } from "@/lib/matches/conceded";
import { sheet } from "@/lib/matches/sheet";
import type { GoalItem } from "@/lib/view2d/review";

export const metadata: Metadata = { robots: { index: false } };

const MODES = ["detections", "goals", "windows"] as const;
type Mode = (typeof MODES)[number];

/**
 * The labeling mode of the 2D view (T12.7, DV4), in development only: verdicts on the detections,
 * the blind review of the goals conceded (T15.4), and windows of play for the recall (T17.1). A
 * production build has no such page, and its export answers 404 too.
 */
export default async function LabelsPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { id } = await params;
  const asked = (await searchParams).mode;
  const mode: Mode = MODES.find((known) => known === asked) ?? "detections";
  const data = await sheet(id);
  const t = await getTranslations("match");
  const players = data.players.map((player) => ({
    id: player.match_player_id,
    name: player.name,
    team: player.team,
    isMe: player.is_me,
  }));
  // Blind: the goals carry what the analysis found, for the file only.
  const goals: GoalItem[] = data.situations
    .filter((situation) => situation.kind === "goal_context" && situation.game_time_s !== null)
    .map((situation) => ({
      timeS: situation.time_s,
      clockS: situation.game_time_s ?? 0,
      windowS: typeof situation.details.window_s === "number" ? situation.details.window_s : 10,
      detected: situation.tags.filter((tag): tag is GoalTag => GOAL_TAGS.includes(tag as GoalTag)),
    }));

  return (
    <div className="flex flex-col gap-6">
      <Link
        href={`/matches/${id}`}
        className="text-sm text-slate-600 underline dark:text-slate-400"
      >
        {t("labels.back")}
      </Link>
      <nav aria-label={t("labels.modes.label")} className="flex flex-wrap gap-1 text-sm">
        {MODES.map((known) => (
          <Link
            key={known}
            href={`/matches/${id}/labels?mode=${known}`}
            aria-current={known === mode ? "page" : undefined}
            className="rounded-md px-3 py-1.5 text-slate-600 hover:bg-slate-100 aria-[current=page]:bg-slate-900 aria-[current=page]:text-white dark:text-slate-300 dark:hover:bg-slate-800 dark:aria-[current=page]:bg-slate-100 dark:aria-[current=page]:text-slate-900"
          >
            {t(`labels.modes.${known}`)}
          </Link>
        ))}
      </nav>
      <MatchView
        matchId={id}
        players={players}
        gameLengthS={data.match.game_length_s}
        overtimeFromS={data.match.overtime_from_s}
        markSituations={mode === "detections"}
      />
      {mode === "detections" ? <LabelQueue matchId={id} players={players} /> : null}
      {mode === "goals" ? <GoalReview key={id} matchId={id} goals={goals} /> : null}
      {mode === "windows" ? <WindowReview key={id} matchId={id} /> : null}
    </div>
  );
}
