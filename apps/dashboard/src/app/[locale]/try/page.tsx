import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { LicenceNotice } from "@/components/LicenceNotice";
import { TryIt } from "@/components/TryIt";
import content from "@/content/try.json";
import { isLocale, t } from "@/lib/i18n";
import { alternatesFor } from "@/lib/paths";
import { DEMO_API_URL, DEMO_TIMEOUT_S, licences } from "@/lib/site";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  return {
    title: `Prüfstand · ${isLocale(locale) ? t(locale, "try.title") : ""}`,
    alternates: alternatesFor("try"),
  };
}

/** Try it (ui-spec §4.6): without `NEXT_PUBLIC_DEMO_API_URL` at build the page only says it is unavailable. */
export default async function TryPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  return (
    <>
      <h1>{t(locale, "try.title")}</h1>
      {DEMO_API_URL === "" ? (
        <p data-state="T-DISABLED">{t(locale, "try.unavailable")}</p>
      ) : (
        <TryIt
          locale={locale}
          apiUrl={DEMO_API_URL}
          timeoutS={DEMO_TIMEOUT_S}
          tenants={content.tenants}
          examples={content.examples}
        />
      )}
      <LicenceNotice locale={locale} licences={licences} variant="full" />
    </>
  );
}
