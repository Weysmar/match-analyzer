import Link from "next/link";
import { getTranslations } from "next-intl/server";

export default async function Home() {
  const t = await getTranslations("home");
  return (
    <div className="flex flex-col gap-10">
      <section className="flex flex-col gap-4">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">{t("title")}</h1>
        <p className="max-w-2xl text-lg text-slate-600 dark:text-slate-300">{t("lead")}</p>
        <div>
          <Link
            href="/upload"
            className="inline-block rounded-lg bg-slate-900 px-5 py-3 font-medium text-white hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
          >
            {t("cta")}
          </Link>
        </div>
      </section>
      <section className="flex flex-col gap-3">
        <h2 className="text-xl font-semibold">{t("metrics.title")}</h2>
        <ul className="grid gap-3 sm:grid-cols-3">
          {(["boost", "movement", "positioning"] as const).map((key) => (
            <li
              key={key}
              className="rounded-lg border border-slate-200 p-4 text-sm dark:border-slate-800"
            >
              {t(`metrics.${key}`)}
            </li>
          ))}
        </ul>
      </section>
      <p className="text-sm text-slate-500 dark:text-slate-400">{t("pcOnly")}</p>
    </div>
  );
}
