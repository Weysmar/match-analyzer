"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { type ReactNode, useEffect, useState } from "react";
import { VERDICTS, type Verdict } from "@/lib/view2d/labels";
import { viewLinkKeeping } from "@/lib/view2d/links";
import type { AnyLabelFile } from "@/lib/view2d/review";

export interface ReviewItem {
  /** Where the player is set, in seconds of play, paused. */
  seekClockS: number;
  /** What is on screen: the goal, or the window and its bounds. */
  heading: ReactNode;
}

/**
 * A blind review (T15.4, T17.1), in development only: one item at a time, the 2D view set at its
 * start, a few questions answered "yes", "no" or "uncertain", then the export to
 * `tests/fixtures/labels/`. What the analysis found is never shown: it only goes into the file.
 */
export function BlindReview<Key extends string>({
  title,
  intro,
  items,
  questions,
  buildFile,
}: {
  title: string;
  intro: string;
  items: readonly ReviewItem[];
  questions: readonly { key: Key; label: string }[];
  buildFile: (verdicts: ReadonlyMap<number, Partial<Record<Key, Verdict>>>) => AnyLabelFile;
}) {
  const t = useTranslations("match.labels");
  const router = useRouter();
  const [current, setCurrent] = useState(0);
  const [verdicts, setVerdicts] = useState<Map<number, Partial<Record<Key, Verdict>>>>(new Map());
  const [saved, setSaved] = useState<string | null>(null);
  const item = items[current];

  // The player follows the queue: paused, at the start of the item, the mode kept.
  useEffect(() => {
    if (item) {
      router.replace(viewLinkKeeping(item.seekClockS, window.location.search), {
        scroll: false,
      });
    }
  }, [item, router]);

  if (items.length === 0) return <p className="text-sm">{t("review.empty")}</p>;

  const given: Partial<Record<Key, Verdict>> = verdicts.get(current) ?? {};
  const judged = [...verdicts.values()].filter((answers) => Object.keys(answers).length > 0).length;

  function answer(key: Key, verdict: Verdict) {
    setVerdicts((previous) => new Map(previous).set(current, { ...given, [key]: verdict }));
    setSaved(null);
  }

  async function exportAll() {
    const response = await fetch("/dev/labels", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildFile(verdicts)),
    });
    if (!response.ok) {
      setSaved(t("exportError"));
      return;
    }
    const body = (await response.json()) as { file: string };
    setSaved(t("exported", { files: body.file }));
  }

  const button =
    "rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800";
  const choice =
    "rounded-md border border-slate-300 px-2 py-1 text-xs font-medium hover:bg-slate-100 aria-pressed:bg-slate-900 aria-pressed:text-white dark:border-slate-700 dark:hover:bg-slate-800 dark:aria-pressed:bg-slate-100 dark:aria-pressed:text-slate-900";

  return (
    <section
      aria-labelledby="review-title"
      className="flex flex-col gap-3 rounded-lg border border-amber-400 p-4"
    >
      <h2 id="review-title" className="text-lg font-semibold">
        {title}
      </h2>
      <p className="text-xs text-slate-600 dark:text-slate-400">{intro}</p>
      <p className="text-xs text-slate-600 dark:text-slate-400">{t("devOnly")}</p>
      <p className="text-sm tabular-nums">
        {t("review.progress", { current: current + 1, total: items.length, done: judged })}
      </p>
      {item ? (
        <div className="flex flex-col gap-3">
          <div className="text-sm font-medium">{item.heading}</div>
          <ul className="flex flex-col divide-y divide-slate-100 dark:divide-slate-900">
            {questions.map((question) => (
              <li key={question.key} className="py-1.5">
                <fieldset className="flex flex-wrap items-center justify-between gap-2">
                  <legend className="float-left text-sm">{question.label}</legend>
                  <span className="flex gap-1">
                    {VERDICTS.map((verdict) => (
                      <button
                        key={verdict}
                        type="button"
                        className={choice}
                        aria-pressed={given[question.key] === verdict}
                        onClick={() => answer(question.key, verdict)}
                      >
                        {t(`review.answer.${verdict}`)}
                      </button>
                    ))}
                  </span>
                </fieldset>
              </li>
            ))}
          </ul>
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
              disabled={current >= items.length - 1}
              onClick={() => setCurrent((index) => Math.min(items.length - 1, index + 1))}
            >
              {t("next")}
            </button>
            <button type="button" className={button} onClick={exportAll} disabled={judged === 0}>
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
