"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import type { Schemas } from "@/lib/api/client";
import { show, type Unit } from "@/lib/matches/metrics";
import { geometry, PADDING } from "@/lib/stats/chart";

const HEIGHT = 200;

/**
 * One metric over the last matches (T8.13), drawn in SVG: positions are attributes, which the
 * security policy allows (A65). One series, so no legend: the heading names it. Unverified matches
 * are hollow, so the difference does not rest on color. A table gives every value.
 */
export function HistoryChart({
  points,
  unit,
  label,
}: {
  points: Schemas["HistoryPoint"][];
  unit: Unit;
  label: string;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const box = useRef<HTMLDivElement>(null);
  // The server cannot know the width: start narrow, then fit the box once measured.
  const [width, setWidth] = useState(320);
  const [active, setActive] = useState<number | null>(null);

  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const fitTo = (measured: number) => setWidth(Math.max(200, Math.round(measured)));
    // Measured at once: an observer only reports at the next rendering step, which a page in a
    // background tab may not reach for a while.
    fitTo(element.getBoundingClientRect().width);
    const observer = new ResizeObserver(([entry]) => {
      if (entry) fitTo(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const shape = geometry(points, width, HEIGHT);

  function text(value: number | null) {
    const shown = show(value, unit);
    if (!shown) return t("units.none");
    return t(`units.${shown.unit}`, {
      value: format.number(shown.value, { maximumFractionDigits: shown.digits }),
    });
  }

  function date(playedAt: string | null) {
    return playedAt
      ? format.dateTime(new Date(playedAt), { dateStyle: "medium" })
      : t("matches.unknownDate");
  }

  if (shape.points.length === 0) {
    return <p className="text-sm text-slate-600 dark:text-slate-400">{t("stats.chart.empty")}</p>;
  }

  const hovered = active === null ? null : shape.points[active];
  const tipWidth = 150;
  const tipX = hovered ? Math.min(Math.max(hovered.x - tipWidth / 2, 0), width - tipWidth) : 0;
  const tipY = hovered ? (hovered.y > 60 ? hovered.y - 54 : hovered.y + 14) : 0;

  return (
    <figure className="flex flex-col gap-2">
      <div ref={box} className="w-full min-w-0 overflow-x-clip">
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={t("stats.chart.label", { metric: label, count: shape.points.length })}
          className="overflow-visible"
          onMouseLeave={() => setActive(null)}
        >
          {shape.ticks.map((tick) => (
            <g key={tick.value}>
              <line
                x1={PADDING.left}
                x2={width - PADDING.right}
                y1={tick.y}
                y2={tick.y}
                strokeWidth="1"
                className="stroke-slate-200 dark:stroke-slate-800"
              />
              <text
                x={PADDING.left - 8}
                y={tick.y}
                textAnchor="end"
                dominantBaseline="middle"
                className="fill-slate-500 text-[11px] dark:fill-slate-400"
              >
                {text(tick.value)}
              </text>
            </g>
          ))}
          {shape.path ? (
            <path
              d={shape.path}
              fill="none"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="stroke-sky-600 dark:stroke-sky-400"
            />
          ) : null}
          {shape.points.map((point, index) => (
            // biome-ignore lint/a11y/noStaticElementInteractions: the table below gives the same values to every reader.
            <g
              key={point.matchId}
              onMouseEnter={() => setActive(index)}
              onFocus={() => setActive(index)}
              onBlur={() => setActive(null)}
              tabIndex={0}
              className="outline-none"
            >
              <circle cx={point.x} cy={point.y} r="12" fill="transparent" />
              <circle
                cx={point.x}
                cy={point.y}
                r="4"
                strokeWidth="2"
                className={
                  point.verified
                    ? "fill-sky-600 stroke-white dark:fill-sky-400 dark:stroke-slate-950"
                    : "fill-white stroke-sky-600 dark:fill-slate-950 dark:stroke-sky-400"
                }
              />
              {active === index ? (
                <circle
                  cx={point.x}
                  cy={point.y}
                  r="8"
                  fill="none"
                  strokeWidth="1"
                  className="stroke-slate-400"
                />
              ) : null}
            </g>
          ))}
          {hovered ? (
            <g pointerEvents="none">
              <rect
                x={tipX}
                y={tipY}
                width={tipWidth}
                height="42"
                rx="6"
                className="fill-white stroke-slate-300 dark:fill-slate-900 dark:stroke-slate-700"
              />
              <text
                x={tipX + 10}
                y={tipY + 17}
                className="fill-slate-900 text-[13px] font-semibold dark:fill-slate-100"
              >
                {text(hovered.value)}
              </text>
              <text
                x={tipX + 10}
                y={tipY + 33}
                className="fill-slate-500 text-[11px] dark:fill-slate-400"
              >
                {date(hovered.playedAt)}
                {hovered.verified ? "" : ` · ${t("matches.unverified")}`}
              </text>
            </g>
          ) : null}
        </svg>
      </div>
      <figcaption className="text-xs text-slate-500 dark:text-slate-400">
        {t("stats.chart.caption")}
      </figcaption>
      <details className="text-sm">
        <summary className="cursor-pointer text-slate-600 dark:text-slate-400">
          {t("stats.chart.table")}
        </summary>
        <table className="mt-2 w-full text-left">
          <thead className="text-xs text-slate-500">
            <tr>
              <th scope="col" className="py-1 font-medium">
                {t("stats.chart.date")}
              </th>
              <th scope="col" className="py-1 text-right font-medium">
                {label}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-900">
            {points.map((point) => (
              <tr key={point.match_id}>
                <td className="py-1">
                  {date(point.played_at)}
                  {point.verified ? null : (
                    <span className="ml-2 text-xs text-slate-500">({t("matches.unverified")})</span>
                  )}
                </td>
                <td className="py-1 text-right tabular-nums">{text(point.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
