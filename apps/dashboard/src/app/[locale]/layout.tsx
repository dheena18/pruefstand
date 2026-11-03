import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { AppFooter } from "@/components/AppFooter";
import { ThemeInit } from "@/components/ThemeInit";
import { AppHeader } from "@/components/AppHeader";
import { LOCALES, isLocale, t } from "@/lib/i18n";
import { BASE_PATH, DEMO_API_URL, GITHUB_URL, footerInfo, licences } from "@/lib/site";

import type { Metadata } from "next";

export const dynamicParams = false;

// Only resolves relative URLs of `alternates`; GitHub Pages of the public repo.
export const metadata: Metadata = { metadataBase: new URL("https://dheena18.github.io") };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

/** The locale document: `<html lang={locale}>`, theme file in `<head>`, skip link, header, footer. */
export default async function LocaleLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const info = await footerInfo();
  return (
    <html lang={locale} suppressHydrationWarning>
      <head>
        <ThemeInit />
      </head>
      <body>
        <a className="skip-link" href="#content">
          {t(locale, "nav.skip")}
        </a>
        <AppHeader locale={locale} demoEnabled={DEMO_API_URL !== ""} githubUrl={GITHUB_URL} />
        <main id="content" className="app-main" tabIndex={-1}>
          {children}
        </main>
        <AppFooter locale={locale} licences={licences} info={info} basePath={BASE_PATH} />
      </body>
    </html>
  );
}
