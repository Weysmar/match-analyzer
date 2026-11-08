import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { LegalPage } from "@/components/LegalPage";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("legal");
  return { title: t("legal.title") };
}

export default function LegalNoticePage() {
  return <LegalPage page="legal" />;
}
