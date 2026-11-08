import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import { SiteHeader } from "@/components/SiteHeader";
import type { Me } from "@/lib/api/client";
import { serverGet } from "@/lib/api/server";
import "./globals.css";

// Every page carries a fresh nonce in its security policy: none can be built in advance.
export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("app");
  return { title: t("name"), description: t("tagline") };
}

async function whoIsThere(): Promise<Me | null> {
  try {
    return await serverGet("/api/v1/me");
  } catch {
    // The API being down must not take the site with it.
    return null;
  }
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  const me = await whoIsThere();
  return (
    <html lang={locale}>
      <body className="min-h-dvh bg-white text-slate-900 antialiased dark:bg-slate-950 dark:text-slate-100">
        <NextIntlClientProvider>
          <SiteHeader me={me} />
          <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
