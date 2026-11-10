/**
 * The causes of the goals the player's team conceded over their last matches (T16.4): for each tag
 * of a goal's context, how many of those goals carry it, and what share of them that is. A goal
 * may carry several tags, or none: the shares do not add up to 100.
 */
import type { Schemas } from "@/lib/api/client";
import { GOAL_TAGS, type GoalTag } from "@/lib/matches/conceded";

export interface Cause {
  tag: GoalTag;
  goals: number;
  /** From 0 to 100. */
  share: number;
}

/** The tags found, most frequent first, then in the cards' order; none without goals conceded. */
export function causes(conceded: Schemas["Conceded"]): Cause[] {
  if (conceded.goals <= 0) return [];
  return GOAL_TAGS.flatMap((tag) => {
    const goals = conceded.tags[tag] ?? 0;
    return goals > 0 ? [{ tag, goals, share: (100 * goals) / conceded.goals }] : [];
  }).sort((a, b) => b.goals - a.goals || GOAL_TAGS.indexOf(a.tag) - GOAL_TAGS.indexOf(b.tag));
}

/** The share of the goals conceded with none of the usual causes found, from 0 to 100. */
export function untaggedShare(conceded: Schemas["Conceded"]): number {
  return conceded.goals > 0 ? (100 * conceded.untagged) / conceded.goals : 0;
}
