import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { UploadPanel } from "@/components/upload/UploadPanel";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("upload");
  return { title: t("title") };
}

export default async function UploadPage() {
  const t = await getTranslations("upload");
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("title")}</h1>
        <p className="max-w-2xl text-slate-600 dark:text-slate-300">{t("lead")}</p>
      </header>
      <UploadPanel />
    </div>
  );
}
