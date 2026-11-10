"use client";

import { useTranslations } from "next-intl";
import { useMemo } from "react";
import { formatClock } from "@/lib/matches/timeline";
import { RECALL_DETECTORS, recallWindows, windowLabelFile } from "@/lib/view2d/review";
import { BlindReview } from "./BlindReview";
import { useView } from "./useView";

/**
 * Windows of play for the recall (T17.1): 10 s before each goal and a few at random, each detector
 * judged there or not. Whether it found one is in the queue, for the file only.
 */
export function WindowReview({ matchId }: { matchId: string }) {
  const t = useTranslations("match");
  const { status, view } = useView(matchId);
  const queue = useMemo(() => (view ? recallWindows(view, matchId) : []), [view, matchId]);
  if (status !== "ready") {
    return <p className="text-sm">{t(status === "loading" ? "labels.loading" : "labels.none")}</p>;
  }
  return (
    <BlindReview
      title={t("labels.windows.title")}
      intro={t("labels.windows.intro")}
      items={queue.map((window) => ({
        seekClockS: window.startClockS,
        heading: t(`labels.windows.heading.${window.source}`, {
          start: formatClock(window.startClockS),
          end: formatClock(window.endClockS),
        }),
      }))}
      questions={RECALL_DETECTORS.map((detector) => ({
        key: detector,
        label: t(`analysis.kinds.${detector}`),
      }))}
      buildFile={(verdicts) => windowLabelFile(matchId, queue, verdicts, new Date())}
    />
  );
}
