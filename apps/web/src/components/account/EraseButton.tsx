"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { sendJson } from "@/lib/api/client";

/**
 * The right to erasure (section 11 of CLAUDE.md), in two clicks: the first one asks, the second one
 * erases. Erasing the account also signs out: the API clears the cookies.
 */
export function EraseButton({ what }: { what: "account" | "session" }) {
  const t = useTranslations(`settings.erase.${what}`);
  const tc = useTranslations("settings.erase");
  const router = useRouter();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function erase() {
    setBusy(true);
    setFailed(false);
    try {
      await sendJson("DELETE", what === "account" ? "/api/v1/me" : "/api/v1/me/anonymous");
      router.push("/?erased=1");
      router.refresh();
    } catch {
      setFailed(true);
      setBusy(false);
    }
  }

  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        className="self-start rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950"
      >
        {t("button")}
      </button>
    );
  }

  return (
    <div
      role="alertdialog"
      aria-labelledby={`erase-${what}`}
      className="flex flex-col gap-3 rounded-lg border border-red-300 p-4 dark:border-red-800"
    >
      <p id={`erase-${what}`} className="text-sm">
        {t("confirmText")}
      </p>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={erase}
          disabled={busy}
          className="rounded-lg bg-red-700 px-4 py-2 text-sm font-medium text-white hover:bg-red-800 disabled:opacity-50"
        >
          {t("confirm")}
        </button>
        <button
          type="button"
          onClick={() => setAsking(false)}
          disabled={busy}
          className="rounded-lg px-4 py-2 text-sm underline"
        >
          {tc("cancel")}
        </button>
      </div>
      {failed ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {tc("failed")}
        </p>
      ) : null}
    </div>
  );
}
