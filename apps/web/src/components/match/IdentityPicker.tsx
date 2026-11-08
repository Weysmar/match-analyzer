"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ApiError, sendJson } from "@/lib/api/client";

interface Candidate {
  id: number;
  name: string;
  team: number;
}

/**
 * "Which of these players are you?" (T8.7). The API remembers the choice for the next matches; a
 * choice never verifies a match, only a linked game account does.
 */
export function IdentityPicker({
  matchId,
  players,
  meId,
  verified,
  open,
}: {
  matchId: string;
  players: Candidate[];
  meId: number | null;
  verified: boolean;
  open: boolean;
}) {
  const t = useTranslations("match.identity");
  const router = useRouter();
  const [choosing, setChoosing] = useState(open);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function choose(playerId: number) {
    setBusy(true);
    setError(null);
    try {
      await sendJson(
        "POST",
        "/api/v1/matches/{match_id}/identity",
        { match_player_id: playerId },
        { parameters: { match_id: matchId } },
      );
      setChoosing(false);
      router.refresh();
    } catch (failure) {
      setError(
        failure instanceof ApiError && failure.code === "identity_locked"
          ? t("locked")
          : t("error"),
      );
    } finally {
      setBusy(false);
    }
  }

  if (players.length === 0) return null;

  if (!choosing) {
    if (meId === null) return null;
    return (
      <div className="flex flex-wrap items-center gap-3 text-sm">
        {!verified ? (
          <span
            title={t("unverifiedHint")}
            className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200"
          >
            {t("unverified")}
          </span>
        ) : null}
        {!verified ? (
          <span className="text-slate-600 dark:text-slate-400">{t("unverifiedHint")}</span>
        ) : null}
        {!verified ? (
          <button type="button" onClick={() => setChoosing(true)} className="underline">
            {t("change")}
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <section
      aria-labelledby="identity-question"
      className="flex flex-col gap-3 rounded-lg border border-slate-300 p-4 dark:border-slate-700"
    >
      <h2 id="identity-question" className="text-lg font-semibold">
        {t("question")}
      </h2>
      <p className="text-sm text-slate-600 dark:text-slate-400">{t("hint")}</p>
      <ul className="flex flex-wrap gap-2">
        {players.map((player) => (
          <li key={player.id}>
            <button
              type="button"
              disabled={busy}
              aria-pressed={player.id === meId}
              aria-label={`${t("choose")} : ${player.name}`}
              onClick={() => choose(player.id)}
              className={`rounded-lg border px-3 py-2 text-sm font-medium disabled:opacity-50 aria-pressed:ring-2 aria-pressed:ring-slate-900 dark:aria-pressed:ring-slate-100 ${
                player.team === 0
                  ? "border-sky-300 hover:bg-sky-50 dark:border-sky-800 dark:hover:bg-sky-950"
                  : "border-orange-300 hover:bg-orange-50 dark:border-orange-800 dark:hover:bg-orange-950"
              }`}
            >
              {player.name}
            </button>
          </li>
        ))}
      </ul>
      {error ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {error}
        </p>
      ) : null}
      {!open ? (
        <button
          type="button"
          onClick={() => setChoosing(false)}
          className="self-start text-sm underline"
        >
          {t("cancel")}
        </button>
      ) : null}
    </section>
  );
}
