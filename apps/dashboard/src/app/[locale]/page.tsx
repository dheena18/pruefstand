import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { EmptyState } from "@/components/EmptyState";
import { RunsList } from "@/components/RunsList";
import { RunsListView } from "@/components/RunsListView";
import { loadRunIndex } from "@/lib/data";
import { isLocale, t } from "@/lib/i18n";
import { alternatesFor } from "@/lib/paths";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  return {
    title: `Prüfstand · ${isLocale(locale) ? t(locale, "runs.title") : ""}`,
    alternates: alternatesFor(""),
  };
}

/**
 * Runs list (ui-spec §4.1): `runs/index.json` is read at build time and embedded. The static HTML is the
 * default view (page 1, created desc) rendered as the `<Suspense>` fallback around the `useSearchParams`
 * reader, so it is never a skeleton (UI11-09). An empty index shows `L-EMPTY`.
 */
export default async function RunsPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const { runs } = await loadRunIndex();
  if (runs.length === 0) {
    return (
      <div data-state="L-EMPTY">
        <EmptyState title={t(locale, "empty.runs")} text={t(locale, "empty.runs_hint")} />
      </div>
    );
  }
  return (
    <Suspense fallback={<RunsListView locale={locale} runs={runs} query="" />}>
      <RunsList locale={locale} runs={runs} />
    </Suspense>
  );
}
