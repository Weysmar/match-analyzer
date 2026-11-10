"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";
import { formatClock } from "@/lib/matches/timeline";
import {
  DETECTORS,
  labelFile,
  labelQueue,
  type QueueItem,
  VERDICTS,
  type Verdict,
} from "@/lib/view2d/labels";
import { LEAD_S, viewLink } from "@/lib/view2d/links";
import type { ViewPlayer } from "./MatchView";
import { useView } from "./useView";

/**
 * The labeling mode (T12.7), next to the player: one situation at a time, the view set a few
 * seconds before it, three verdicts, then the export to `tests/fixtures/labels/`.
 */
export function LabelQueue({ matchId, players }: { matchId: string; players: ViewPlayer[] }) {
  const t = useTranslations("match.labels");
  const router = useRouter();
  const { status, view } = useView(matchId);
  const queue = useMemo(() => (view ? labelQueue(view, matchId) : []), [view, matchId]);
  const [current, setCurrent] = useState(0);
  const [verdicts, setVerdicts] = useState<Map<number, Verdict>>(new Map());
  const [saved, setSaved] = useState<string | null>(null);
  const item: QueueItem | undefined = queue[current];

  // The player follows the queue: paused, a few seconds before the situation.
  useEffect(() => {
    if (item) router.replace(viewLink(item.clockS - LEAD_S), { scroll: false });
  }, [item, router]);

  if (status !== "ready")
    return <p className="text-sm">{t(status === "loading" ? "loading" : "none")}</p>;
  if (queue.length === 0) return <p className="text-sm">{t("empty")}</p>;

  const name = (id: number | undefined) =>
    players.find((player) => player.id === id)?.name ?? t("unknownPlayer");

  /** Who the situation is about, as its kind tells it. */
  function who(situation: QueueItem): string {
    const [first, second] = situation.players;
    if (situation.detector === "turnover") {
      return second === undefined
        ? t("turnoverWinner", { won: name(first) })
        : t("turnoverPlayers", { won: name(first), lost: name(second) });
    }
    if (situation.detector === "overcommit") {
      return t("overcommitPlayers", { players: situation.players.map(name).join(", ") });
    }
    if (situation.detector === "double_commit") {
      return t("doubleCommitPlayers", { players: situation.players.map(name).join(", ") });
    }
    if (situation.detector === "fifty_fifty") {
      return t("duelPlayers", { blue: name(first), orange: name(second) });
    }
    return situation.players.length > 0
      ? t("kickoffTakers", { takers: situation.players.map(name).join(", ") })
      : t("kickoffNoTaker");
  }

  function judge(verdict: Verdict) {
    setVerdicts((previous) => new Map(previous).set(current, verdict));
    setSaved(null);
    setCurrent((index) => Math.min(queue.length - 1, index + 1));
  }

  async function exportAll() {
    const written: string[] = [];
    for (const detector of DETECTORS) {
      const file = labelFile(matchId, detector, queue, verdicts, new Date());
      if (file.labels.length === 0) continue;
      const response = await fetch("/dev/labels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(file),
      });
      if (!response.ok) {
        setSaved(t("exportError"));
        return;
      }
      const body = (await response.json()) as { file: string };
      written.push(body.file);
    }
    setSaved(written.length ? t("exported", { files: written.join(", ") }) : t("nothing"));
  }

  const button =
    "rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800";

  return (
    <section
      aria-labelledby="labels-title"
      className="flex flex-col gap-3 rounded-lg border border-amber-400 p-4"
    >
      <h2 id="labels-title" className="text-lg font-semibold">
        {t("title")}
      </h2>
      <p className="text-xs text-slate-600 dark:text-slate-400">{t("devOnly")}</p>
      <p className="text-sm tabular-nums">
        {t("progress", { done: verdicts.size, total: queue.length, current: current + 1 })}
      </p>
      {item ? (
        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium">
            {t(`kind.${item.detector}`, { clock: formatClock(item.clockS) })}
          </p>
          <p className="text-sm">{who(item)}</p>
          <div className="flex flex-wrap gap-2">
            {VERDICTS.map((verdict) => (
              <button
                key={verdict}
                type="button"
                className={`${button} ${verdicts.get(current) === verdict ? "bg-slate-200 dark:bg-slate-700" : ""}`}
                aria-pressed={verdicts.get(current) === verdict}
                onClick={() => judge(verdict)}
              >
                {t(`verdict.${verdict}`)}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className={button}
              disabled={current === 0}
              onClick={() => setCurrent((index) => Math.max(0, index - 1))}
            >
              {t("previous")}
            </button>
            <button
              type="button"
              className={button}
              disabled={current >= queue.length - 1}
              onClick={() => setCurrent((index) => Math.min(queue.length - 1, index + 1))}
            >
              {t("next")}
            </button>
            <button
              type="button"
              className={button}
              onClick={exportAll}
              disabled={verdicts.size === 0}
            >
              {t("export")}
            </button>
          </div>
        </div>
      ) : null}
      {saved ? (
        <p role="status" className="text-sm">
          {saved}
        </p>
      ) : null}
    </section>
  );
}
