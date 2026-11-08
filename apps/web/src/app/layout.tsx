import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import { SiteFooter } from "@/components/SiteFooter";
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
  const t = await getTranslations("header");
  return (
    <html lang={locale}>
      <body className="flex min-h-dvh flex-col bg-white text-slate-900 antialiased dark:bg-slate-950 dark:text-slate-100">
        <NextIntlClientProvider>
          {/* First stop of the keyboard: straight past the header (T8.15). */}
          <a
            href="#content"
            className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-20 focus:rounded-md focus:bg-slate-900 focus:px-3 focus:py-2 focus:text-white"
          >
            {t("skip")}
          </a>
          <SiteHeader me={me} />
          <main id="content" tabIndex={-1} className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
            {children}
          </main>
          <SiteFooter />
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
