"use client";

import { useSearchParams } from "next/navigation";
import { useFormatter, useTranslations } from "next-intl";
import { type KeyboardEvent, useCallback, useEffect, useReducer, useRef, useState } from "react";
import { formatClock, readClock, regulationOf } from "@/lib/matches/timeline";
import { drawScene } from "@/lib/view2d/draw";
import { type Layout, layoutFor } from "@/lib/view2d/field";
import { parseT, VIEW_ANCHOR } from "@/lib/view2d/links";
import { type Action, actionForKey, reduce, SPEEDS, START } from "@/lib/view2d/playback";
import { sceneAt } from "@/lib/view2d/scene";
import { clockAt, durationS, goalMarkers, timeAtClock } from "@/lib/view2d/time";
import { useView } from "./useView";

export interface ViewPlayer {
  id: number;
  name: string;
  team: number;
  isMe: boolean;
}

// The field never takes more than this share of the window's height.
const MAX_HEIGHT_SHARE = 0.7;

/**
 * The 2D view of a match (T12.3 to T12.6): the field from above, the cars and the ball, played back
 * from the analysis's document. Nothing moves until the visitor presses play. `?t=` in the
 * address, such as a goal's link, sets it at that many seconds of play, paused.
 */
export function MatchView({
  matchId,
  players,
  gameLengthS,
  overtimeFromS,
}: {
  matchId: string;
  players: ViewPlayer[];
  gameLengthS: number | null;
  overtimeFromS: number | null;
}) {
  const t = useTranslations("match.view");
  const format = useFormatter();
  const { status, view } = useView(matchId);
  const [layout, setLayout] = useState<Layout | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const section = useRef<HTMLElement>(null);
  const asked = parseT(useSearchParams().get("t"));
  const canvas = useRef<HTMLCanvasElement>(null);
  const duration = view ? durationS(view) : 0;
  const [playback, dispatch] = useReducer(
    (state: typeof START, action: Action) => reduce(state, action, duration),
    START,
  );
  const meId = players.find((player) => player.isMe)?.id ?? null;

  // The field fits the player's width, on its side when there is room.
  useEffect(() => {
    const element = box.current;
    if (!element || status !== "ready") return;
    const measure = () =>
      setLayout(layoutFor(element.clientWidth, window.innerHeight * MAX_HEIGHT_SHARE));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [status]);

  // A link into the view: there, paused, in sight. Without a sweeping scroll for whoever asked
  // their system for less motion.
  useEffect(() => {
    if (!view || asked === null) return;
    dispatch({ type: "pause" });
    dispatch({ type: "seek", t: timeAtClock(view, asked) });
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    section.current?.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start" });
  }, [view, asked]);

  // One frame per screen refresh while playing, nothing otherwise.
  useEffect(() => {
    if (!playback.playing) return;
    let last = performance.now();
    let frame = requestAnimationFrame(function step(now) {
      dispatch({ type: "tick", elapsedS: (now - last) / 1000 });
      last = now;
      frame = requestAnimationFrame(step);
    });
    return () => cancelAnimationFrame(frame);
  }, [playback.playing]);

  useEffect(() => {
    const element = canvas.current;
    const pen = element?.getContext("2d");
    if (!element || !pen || !view || !layout) return;
    const ratio = window.devicePixelRatio || 1;
    element.width = Math.round(layout.width * ratio);
    element.height = Math.round(layout.height * ratio);
    // CSSOM, not a style attribute: the security policy refuses those (A65).
    element.style.width = `${layout.width}px`;
    element.style.height = `${layout.height}px`;
    pen.setTransform(ratio, 0, 0, ratio, 0, 0);
    drawScene(pen, layout, sceneAt(view, playback.t), meId);
  }, [view, layout, playback.t, meId]);

  const onKeyDown = useCallback((event: KeyboardEvent) => {
    const target = event.target as HTMLElement;
    // A button already answers Space, and the cursor the arrows.
    if (target.tagName === "INPUT" || (event.key === " " && target.tagName === "BUTTON")) return;
    const action = actionForKey(event.key);
    if (action) {
      event.preventDefault();
      dispatch(action);
    }
  }, []);

  if (status !== "ready" || !view) {
    const message = { loading: t("loading"), unavailable: t("unavailable"), error: t("error") };
    return (
      <section id={VIEW_ANCHOR} aria-labelledby="view-title" className="flex flex-col gap-3">
        <h2 id="view-title" className="text-lg font-semibold">
          {t("title")}
        </h2>
        <p role="status" className="text-sm text-slate-600 dark:text-slate-400">
          {message[status === "ready" ? "loading" : status]}
        </p>
      </section>
    );
  }

  const regulation = regulationOf(gameLengthS, overtimeFromS);
  const elapsed = clockAt(view, playback.t);
  const shown = readClock(elapsed, overtimeFromS, regulation);
  const clockText = shown.overtime
    ? t("intoOvertime", { clock: formatClock(shown.clockS) })
    : t("remaining", { clock: formatClock(shown.clockS) });
  const lastClock = view.clockS[view.clockS.length - 1] ?? 0;
  const button =
    "rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-600 dark:border-slate-700 dark:hover:bg-slate-800";

  return (
    <section
      ref={section}
      id={VIEW_ANCHOR}
      aria-labelledby="view-title"
      className="flex scroll-mt-4 flex-col gap-3 rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sky-600"
      // biome-ignore lint/a11y/noNoninteractiveTabindex: the player takes Space and the arrows.
      tabIndex={0}
      onKeyDown={onKeyDown}
    >
      <h2 id="view-title" className="text-lg font-semibold">
        {t("title")}
      </h2>
      <div ref={box} className="w-full">
        <canvas
          ref={canvas}
          role="img"
          aria-label={t("canvas")}
          aria-describedby="view-keys"
          className="mx-auto block rounded-lg"
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className={button}
          onClick={() => dispatch({ type: "toggle" })}
          aria-pressed={playback.playing}
        >
          {playback.playing ? t("pause") : t("play")}
        </button>
        <button
          type="button"
          className={button}
          onClick={() => dispatch({ type: "skip", byS: -5 })}
        >
          {t("back")}
        </button>
        <button type="button" className={button} onClick={() => dispatch({ type: "skip", byS: 5 })}>
          {t("forward")}
        </button>
        <fieldset className="flex items-center gap-1">
          <legend className="sr-only">{t("speed")}</legend>
          {SPEEDS.map((speed) => (
            <button
              key={speed}
              type="button"
              className={`${button} ${playback.speed === speed ? "bg-slate-200 dark:bg-slate-700" : ""}`}
              aria-pressed={playback.speed === speed}
              onClick={() => dispatch({ type: "speed", speed })}
            >
              {t("speedValue", { speed: format.number(speed) })}
            </button>
          ))}
        </fieldset>
        <span className="ml-auto text-sm tabular-nums" aria-live="off">
          {clockText}
        </span>
      </div>
      <label className="flex flex-col gap-1 text-sm">
        <span className="sr-only">{t("cursor")}</span>
        {/* SVG attributes, not inline styles: the security policy refuses those (A59). */}
        {/* The goals' list above is their text: here, they only show where they are. */}
        <svg aria-hidden="true" className="h-3 w-full overflow-visible">
          {goalMarkers(view).map((marker, index) => (
            <circle
              // biome-ignore lint/suspicious/noArrayIndexKey: goals keep their order.
              key={index}
              cx={`${marker.left}%`}
              cy="6"
              r="4"
              className={
                marker.team === 0
                  ? "fill-sky-600"
                  : marker.team === 1
                    ? "fill-orange-500"
                    : "fill-slate-400"
              }
            />
          ))}
        </svg>
        <input
          type="range"
          min={0}
          max={Math.max(lastClock, 0.1)}
          step={0.1}
          value={elapsed}
          aria-valuetext={clockText}
          onChange={(event) =>
            dispatch({ type: "seek", t: timeAtClock(view, Number(event.target.value)) })
          }
          className="w-full accent-sky-600"
        />
      </label>
      <p id="view-keys" className="text-xs text-slate-600 dark:text-slate-400">
        {t("keys")}
      </p>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {view.cars.map((car) => {
          const player = players.find((candidate) => candidate.id === car.id);
          return (
            <li key={car.id} className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className={`inline-block h-3 w-3 rounded-sm ${car.team === 0 ? "bg-blue-500" : "bg-amber-500"} ${car.id === meId ? "ring-2 ring-slate-900 dark:ring-white" : ""}`}
              />
              <span>{player?.name ?? t("unknownPlayer")}</span>
              {car.id === meId ? <span className="text-slate-500">({t("you")})</span> : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
