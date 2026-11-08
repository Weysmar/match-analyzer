"use client";

import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { type Item, type Phase, reasonKey } from "@/lib/upload/state";

const TONE: Record<Phase, string> = {
  checking: "text-slate-600 dark:text-slate-400",
  waiting: "text-slate-600 dark:text-slate-400",
  sending: "text-sky-700 dark:text-sky-300",
  processing: "text-sky-700 dark:text-sky-300",
  ready: "text-emerald-700 dark:text-emerald-300",
  duplicate: "text-emerald-700 dark:text-emerald-300",
  partial: "text-amber-700 dark:text-amber-300",
  rejected: "text-red-700 dark:text-red-300",
  failed: "text-red-700 dark:text-red-300",
};

const LINKED: ReadonlySet<Phase> = new Set(["ready", "duplicate", "partial"]);

export function UploadList({ items }: { items: readonly Item[] }) {
  const t = useTranslations("upload");
  const format = useFormatter();
  return (
    <ul className="flex flex-col divide-y divide-slate-200 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
      {items.map((item) => (
        <li key={item.key} className="flex flex-col gap-2 px-4 py-3 text-sm">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <span className="min-w-0 break-all font-medium">{item.name}</span>
            <span className={`shrink-0 ${TONE[item.phase]}`}>{t(`phases.${item.phase}`)}</span>
          </div>
          {item.phase === "sending" ? (
            <progress
              value={Math.round(item.progress * 100)}
              max={100}
              aria-label={t("list.progress", { name: item.name })}
              className="h-2 w-full overflow-hidden rounded-full accent-sky-600"
            />
          ) : null}
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
            <span>
              {format.number(item.size / 1_048_576, { maximumFractionDigits: 1 })} {t("list.mb")}
              {item.reason ? ` · ${t(`reasons.${reasonKey(item.reason)}`)}` : null}
              {item.phase === "partial" ? ` · ${t("list.partial")}` : null}
            </span>
            {item.matchId && LINKED.has(item.phase) ? (
              <Link href={`/matches/${item.matchId}`} className="font-medium underline">
                {t("list.open")}
              </Link>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}
