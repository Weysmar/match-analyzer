import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { Me } from "@/lib/api/client";
import { LocaleSwitch } from "./LocaleSwitch";

export async function SiteHeader({ me }: { me: Me | null }) {
  const t = await getTranslations();
  const who =
    me?.kind === "user" && me.user
      ? t("header.signedInAs", { name: me.user.display_name })
      : me?.kind === "anonymous"
        ? t("header.anonymous")
        : null;
  return (
    <header className="border-b border-slate-200 dark:border-slate-800">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex items-center gap-6">
          <Link href="/" className="font-semibold tracking-tight">
            {t("app.name")}
          </Link>
          <nav aria-label={t("header.nav.label")} className="text-sm">
            <Link href="/upload" className="hover:underline">
              {t("header.nav.upload")}
            </Link>
          </nav>
        </div>
        <div className="flex items-center gap-4">
          {who ? <span className="text-sm text-slate-600 dark:text-slate-400">{who}</span> : null}
          <LocaleSwitch />
        </div>
      </div>
    </header>
  );
}
