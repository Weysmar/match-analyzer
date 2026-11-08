import { getTranslations } from "next-intl/server";

/**
 * A legal page from its messages: a title, then sections of a heading and paragraphs. The texts are
 * drafts until Vincent provides his own (section 11 of CLAUDE.md), and say so.
 */
export async function LegalPage({ page }: { page: "privacy" | "legal" | "terms" }) {
  const t = await getTranslations("legal");
  const sections = t.raw(`${page}.sections`) as { title: string; body: string[] }[];
  return (
    <article className="flex max-w-3xl flex-col gap-6">
      <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t(`${page}.title`)}</h1>
      <p
        role="note"
        className="rounded-lg bg-amber-50 p-4 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100"
      >
        {t("draft")}
      </p>
      {sections.map((section) => (
        <section key={section.title} className="flex flex-col gap-2">
          <h2 className="text-lg font-semibold">{section.title}</h2>
          {section.body.map((paragraph) => (
            <p key={paragraph} className="text-slate-700 dark:text-slate-300">
              {paragraph}
            </p>
          ))}
        </section>
      ))}
    </article>
  );
}
