import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { LicenceNotice } from "@/components/LicenceNotice";
import { isLocale, t } from "@/lib/i18n";
import { alternatesFor } from "@/lib/paths";
import { licences } from "@/lib/site";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  return {
    title: `Prüfstand · ${isLocale(locale) ? t(locale, "licences.title") : ""}`,
    alternates: alternatesFor("licences"),
  };
}

/** Sources and licences (ui-spec §4.7): the source table, the ODbL notice and the offer; MEMERAG is not listed. */
export default async function LicencesPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  return (
    <>
      <h1>{t(locale, "licences.title")}</h1>
      <LicenceNotice locale={locale} licences={licences} variant="full" />
    </>
  );
}
