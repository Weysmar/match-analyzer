import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { EraseButton } from "@/components/account/EraseButton";
import { SignInOptions } from "@/components/account/SignInOptions";
import { serverGet } from "@/lib/api/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("settings");
  return { title: t("title") };
}

const PROVIDERS = ["steam", "epic"] as const;

/** T8.14: linked accounts, and erasure, for an account as for a session without one. */
export default async function SettingsPage() {
  const t = await getTranslations("settings");
  const me = await serverGet("/api/v1/me").catch(() => null);
  const linked = new Set(me?.linked_accounts.map((account) => account.provider));
  const epic = me?.features.epic_login ?? false;
  const missing = PROVIDERS.filter(
    (provider) => !linked.has(provider) && (provider === "steam" || epic),
  );

  return (
    <div className="flex flex-col gap-8">
      <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("title")}</h1>

      {me?.kind === "user" ? (
        <>
          <section aria-labelledby="accounts-title" className="flex flex-col gap-3">
            <h2 id="accounts-title" className="text-lg font-semibold">
              {t("accounts.title")}
            </h2>
            <ul className="flex flex-col divide-y divide-slate-200 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
              {me.linked_accounts.map((account) => (
                <li key={account.provider} className="flex justify-between gap-4 px-4 py-3 text-sm">
                  <span className="font-medium">{t(`accounts.${account.provider}`)}</span>
                  <span className="text-slate-600 dark:text-slate-400">
                    {account.display_name ?? t("accounts.linked")}
                  </span>
                </li>
              ))}
            </ul>
            {missing.length > 0 ? (
              <div className="flex flex-col gap-2">
                <p className="text-sm text-slate-600 dark:text-slate-400">{t("accounts.add")}</p>
                <SignInOptions epic={missing.includes("epic")} returnTo="/settings" />
              </div>
            ) : null}
          </section>
          <section aria-labelledby="erase-title" className="flex flex-col gap-3">
            <h2 id="erase-title" className="text-lg font-semibold">
              {t("erase.title")}
            </h2>
            <p className="max-w-2xl text-sm text-slate-600 dark:text-slate-400">
              {t("erase.account.lead")}
            </p>
            <EraseButton what="account" />
          </section>
        </>
      ) : me?.kind === "anonymous" ? (
        <section aria-labelledby="erase-title" className="flex flex-col gap-3">
          <h2 id="erase-title" className="text-lg font-semibold">
            {t("erase.title")}
          </h2>
          <p className="max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            {t("erase.session.lead")}
          </p>
          <EraseButton what="session" />
        </section>
      ) : (
        <p className="text-slate-600 dark:text-slate-300">{t("nothing")}</p>
      )}
    </div>
  );
}
