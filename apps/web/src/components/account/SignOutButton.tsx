"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { sendJson } from "@/lib/api/client";

export function SignOutButton() {
  const t = useTranslations("account");
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function signOut() {
    setBusy(true);
    try {
      await sendJson("POST", "/api/v1/auth/logout");
    } finally {
      router.push("/");
      router.refresh();
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={signOut}
      disabled={busy}
      className="text-sm underline disabled:opacity-50"
    >
      {t("signOut")}
    </button>
  );
}
