import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { LabelQueue } from "@/components/view2d/LabelQueue";
import { MatchView } from "@/components/view2d/MatchView";
import { sheet } from "@/lib/matches/sheet";

export const metadata: Metadata = { robots: { index: false } };

/**
 * The labeling mode of the 2D view (T12.7, DV4): in development only. A production build has no
 * such page, and its export answers 404 too.
 */
export default async function LabelsPage({ params }: { params: Promise<{ id: string }> }) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { id } = await params;
  const data = await sheet(id);
  const t = await getTranslations("match");
  const players = data.players.map((player) => ({
    id: player.match_player_id,
    name: player.name,
    team: player.team,
    isMe: player.is_me,
  }));

  return (
    <div className="flex flex-col gap-6">
      <Link
        href={`/matches/${id}`}
        className="text-sm text-slate-600 underline dark:text-slate-400"
      >
        {t("labels.back")}
      </Link>
      <MatchView
        matchId={id}
        players={players}
        gameLengthS={data.match.game_length_s}
        overtimeFromS={data.match.overtime_from_s}
      />
      <LabelQueue matchId={id} players={players} />
    </div>
  );
}
