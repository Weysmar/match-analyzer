import Link from "next/link";
import { getTranslations } from "next-intl/server";

export default async function NotFound() {
  const t = await getTranslations("notFound");
  return (
    <div className="flex flex-col items-start gap-4">
      <h1 className="text-2xl font-bold tracking-tight">{t("title")}</h1>
      <p className="text-slate-600 dark:text-slate-300">{t("lead")}</p>
      <Link href="/" className="font-medium underline">
        {t("home")}
      </Link>
    </div>
  );
}
