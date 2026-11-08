import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { Me } from "@/lib/api/client";
import { SignInOptions } from "./account/SignInOptions";
import { SignOutButton } from "./account/SignOutButton";
import { LocaleSwitch } from "./LocaleSwitch";

export async function SiteHeader({ me }: { me: Me | null }) {
  const t = await getTranslations();
  const user = me?.kind === "user" ? me.user : null;
  return (
    <header className="border-b border-slate-200 dark:border-slate-800">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <Link href="/" className="font-semibold tracking-tight">
            {t("app.name")}
          </Link>
          <nav aria-label={t("header.nav.label")} className="flex gap-4 text-sm">
            <Link href="/upload" className="hover:underline">
              {t("header.nav.upload")}
            </Link>
            <Link href="/matches" className="hover:underline">
              {t("header.nav.matches")}
            </Link>
            <Link href="/me/stats" className="hover:underline">
              {t("header.nav.stats")}
            </Link>
          </nav>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          {user ? (
            <>
              <span className="text-sm text-slate-600 dark:text-slate-400">
                {t("header.signedInAs", { name: user.display_name })}
              </span>
              <Link href="/settings" className="text-sm hover:underline">
                {t("header.nav.settings")}
              </Link>
              <SignOutButton />
            </>
          ) : (
            // A disclosure, not a menu script: it works before any JavaScript runs.
            <details className="relative text-sm">
              <summary className="cursor-pointer list-none rounded-md px-2 py-1 font-medium hover:bg-slate-100 dark:hover:bg-slate-800">
                {t("account.signIn")}
              </summary>
              <div className="absolute right-0 z-10 mt-2 flex w-64 flex-col gap-2 rounded-lg border border-slate-200 bg-white p-3 shadow-lg dark:border-slate-800 dark:bg-slate-950">
                <p className="text-xs text-slate-600 dark:text-slate-400">{t("account.why")}</p>
                <SignInOptions epic={me?.features.epic_login ?? false} returnTo="/matches" />
              </div>
            </details>
          )}
          <LocaleSwitch />
        </div>
      </div>
    </header>
  );
}
