import Link from "next/link";
import { getTranslations } from "next-intl/server";

export async function SiteFooter() {
  const t = await getTranslations("footer");
  return (
    <footer className="border-t border-slate-200 dark:border-slate-800">
      <div className="mx-auto flex max-w-5xl flex-col gap-3 px-4 py-6 text-sm text-slate-600 dark:text-slate-400">
        <nav aria-label={t("label")} className="flex flex-wrap gap-x-5 gap-y-2">
          <Link href="/privacy" className="hover:underline">
            {t("privacy")}
          </Link>
          <Link href="/terms" className="hover:underline">
            {t("terms")}
          </Link>
          <Link href="/legal" className="hover:underline">
            {t("legal")}
          </Link>
          <Link href="/settings" className="hover:underline">
            {t("settings")}
          </Link>
        </nav>
        <p className="text-xs">{t("disclaimer")}</p>
      </div>
    </footer>
  );
}
