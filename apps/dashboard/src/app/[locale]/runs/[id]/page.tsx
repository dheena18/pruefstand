import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { EmptyState } from "@/components/EmptyState";
import { isLocale, t } from "@/lib/i18n";

export const dynamicParams = false;

/**
 * T8.1 ships the placeholder only (ui-spec §2.1, Y7.2): `next build` rejects a dynamic route without params,
 * so this page generates `_empty` until T8.2a adds the run summary and its real params. The summary page then
 * falls back to `_empty` again when the index is empty.
 */
export function generateStaticParams() {
  return [{ id: "_empty" }];
}

export function generateMetadata(): Metadata {
  return { robots: { index: false, follow: false } };
}

export default async function RunPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  return (
    <EmptyState
      title={t(locale, "empty.runs")}
      text={t(locale, "empty.runs_hint")}
      action={{ href: `/${locale}/`, label: t(locale, "nav.runs") }}
    />
  );
}
