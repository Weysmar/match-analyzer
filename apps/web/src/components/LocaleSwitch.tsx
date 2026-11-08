"use client";

import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { LOCALE_COOKIE, LOCALES, type Locale } from "@/i18n/locales";

const ONE_YEAR_S = 365 * 24 * 3600;

export function LocaleSwitch() {
  const current = useLocale();
  const router = useRouter();
  const t = useTranslations("header");

  function choose(locale: Locale) {
    // biome-ignore lint/suspicious/noDocumentCookie: a plain preference, read by the server.
    document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=${ONE_YEAR_S}; samesite=lax`;
    router.refresh();
  }

  return (
    <fieldset className="flex items-center gap-1 text-sm">
      <legend className="sr-only">{t("language")}</legend>
      {LOCALES.map((locale) => (
        <button
          key={locale}
          type="button"
          onClick={() => choose(locale)}
          aria-pressed={locale === current}
          lang={locale}
          className="rounded-md px-2 py-1 uppercase text-slate-600 hover:bg-slate-100 aria-pressed:bg-slate-900 aria-pressed:text-white dark:text-slate-300 dark:hover:bg-slate-800 dark:aria-pressed:bg-slate-100 dark:aria-pressed:text-slate-900"
        >
          {locale}
        </button>
      ))}
    </fieldset>
  );
}
