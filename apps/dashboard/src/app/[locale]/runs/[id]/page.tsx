import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { EmptyState } from "@/components/EmptyState";
import { RunSummaryView } from "@/components/RunSummaryView";
import { loadRunIndex } from "@/lib/data";
import { NotFoundError } from "@/lib/errors";
import { refLabel } from "@/lib/format";
import { LOCALES, isLocale, t } from "@/lib/i18n";
import { alternatesFor } from "@/lib/paths";
import { loadRunContext } from "@/lib/run-context";
import { BASE_PATH, GITHUB_URL } from "@/lib/site";

export const dynamicParams = false;

/** Placeholder segment of an empty export (`E-PLACEHOLDER`, Y7.2); never linked, `noindex`. */
const EMPTY_ID = "_empty";

type Params = Promise<{ locale: string; id: string }>;

/** Every run of `runs/index.json` in both locales; an empty index → the `_empty` placeholder. */
export async function generateStaticParams() {
  const { runs } = await loadRunIndex();
  const ids = runs.length === 0 ? [EMPTY_ID] : runs.map((r) => r.run_id);
  return LOCALES.flatMap((locale) => ids.map((id) => ({ locale, id })));
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { id } = await params;
  if (id === EMPTY_ID) return { robots: { index: false }, title: "Prüfstand" };
  const ctx = await loadRunContext(id).catch(() => null);
  return {
    title: `Prüfstand · ${ctx === null ? id : refLabel(ctx.run)}`,
    alternates: alternatesFor(`runs/${id}`),
  };
}

export default async function RunPage({ params }: { params: Params }) {
  const { locale, id } = await params;
  if (!isLocale(locale)) notFound();
  if (id === EMPTY_ID) {
    return <EmptyState title={t(locale, "empty.runs")} text={t(locale, "empty.runs_hint")} />;
  }
  try {
    const ctx = await loadRunContext(id);
    return <RunSummaryView locale={locale} ctx={ctx} basePath={BASE_PATH} githubUrl={GITHUB_URL} />;
  } catch (error) {
    if (error instanceof NotFoundError) notFound();
    throw error;
  }
}
