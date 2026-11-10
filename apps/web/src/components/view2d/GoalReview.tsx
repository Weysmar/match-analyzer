"use client";

import { useTranslations } from "next-intl";
import { useMemo } from "react";
import { GOAL_TAGS } from "@/lib/matches/conceded";
import { formatClock } from "@/lib/matches/timeline";
import { type GoalItem, goalLabelFile, goalQueue } from "@/lib/view2d/review";
import { BlindReview } from "./BlindReview";

/**
 * The blind review of the goals conceded (T15.4): each goal from the start of its context, every
 * tag judged there or not. The tags the analysis gave it are in `goals`, for the file only.
 */
export function GoalReview({ matchId, goals }: { matchId: string; goals: GoalItem[] }) {
  const t = useTranslations("match");
  const queue = useMemo(() => goalQueue(goals, matchId), [goals, matchId]);
  return (
    <BlindReview
      title={t("labels.goals.title")}
      intro={t("labels.goals.intro")}
      items={queue.map((goal) => ({
        seekClockS: Math.max(0, goal.clockS - goal.windowS),
        heading: t("labels.goals.heading", {
          clock: formatClock(goal.clockS),
          window: Math.round(goal.windowS),
        }),
      }))}
      questions={GOAL_TAGS.map((tag) => ({ key: tag, label: t(`conceded.tags.${tag}`) }))}
      buildFile={(verdicts) => goalLabelFile(matchId, queue, verdicts, new Date())}
    />
  );
}
