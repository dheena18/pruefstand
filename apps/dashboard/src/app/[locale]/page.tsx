import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { EmptyState } from "@/components/EmptyState";
import { loadRunIndex } from "@/lib/data";
import { refLabel } from "@/lib/format";
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
 * Runs list shell (ui-spec §4.1 is T8.2a): the heading and, for an empty export, `empty.runs`; otherwise the
 * run references as plain text. Its job in T8.1 is to read and validate the index at build time.
 */
export default async function RunsPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const index = await loadRunIndex();
  if (index.runs.length === 0) {
    return <EmptyState title={t(locale, "empty.runs")} text={t(locale, "empty.runs_hint")} />;
  }
  return (
    <>
      <h1>{t(locale, "runs.title")}</h1>
      <ul className="run-list">
        {index.runs.map((run) => (
          <li key={run.run_id}>
            <span className="mono">{refLabel(run)}</span>
            <span>{run.status ?? "NOT_GATED"}</span>
          </li>
        ))}
      </ul>
    </>
  );
}
