import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { CasesList } from "@/components/CasesList";
import { CasesView } from "@/components/CasesView";
import { RunPageHead } from "@/components/RunPageHead";
import { RunsPlaceholder } from "@/components/RunsPlaceholder";
import { baselineShards } from "@/lib/case-page";
import { applyCases, parseCasesQuery } from "@/lib/cases-state";
import { NotFoundError } from "@/lib/errors";
import { refLabel } from "@/lib/format";
import { isLocale } from "@/lib/i18n";
import { EMPTY_ID } from "@/lib/ids";
import { alternatesFor } from "@/lib/paths";
import { loadRunContext } from "@/lib/run-context";
import { casePublishedRunIds, forLocales, shardZero } from "@/lib/run-pages";

export const dynamicParams = false;

type Params = Promise<{ locale: string; id: string }>;

/** Runs with published case shards (the newest 20, ui-spec §2.3); none → the `_empty` placeholder (UI12-08). */
export async function generateStaticParams() {
  const ids = await casePublishedRunIds();
  return forLocales(
    ids.map((id) => ({ id })),
    { id: EMPTY_ID },
  );
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { id } = await params;
  if (id === EMPTY_ID) return { robots: { index: false }, title: "Prüfstand" };
  const ctx = await loadRunContext(id).catch(() => null);
  return {
    title: `Prüfstand · ${ctx === null ? id : refLabel(ctx.run)} · Cases`,
    alternates: alternatesFor(`runs/${id}/cases`),
  };
}

/**
 * Cases list (ui-spec §4.5.2). Shard 0 is read at build time for the failing count and the static default view
 * ("Failing only", or all when nothing fails); the client then loads the shards and applies the URL query.
 */
export default async function CasesPage({ params }: { params: Params }) {
  const { locale, id } = await params;
  if (!isLocale(locale)) notFound();
  if (id === EMPTY_ID) return <RunsPlaceholder locale={locale} />;
  try {
    const ctx = await loadRunContext(id);
    const shard0 = await shardZero(id);
    if (shard0 === null) notFound();
    const props = {
      locale,
      labels: ctx.labels,
      runId: id,
      nShards: shard0.n_shards,
      shard0Length: shard0.cases.length,
      failingCount: ctx.failing,
      staticRows: applyCases(shard0.cases, parseCasesQuery("", ctx.failing > 0)).rows,
      hardFails: ctx.gate?.hard_fails ?? [],
      baseline: await baselineShards(ctx),
    };
    return (
      <>
        <RunPageHead locale={locale} ctx={ctx} active="cases" />
        <Suspense fallback={<CasesView {...props} query="" live={false} />}>
          <CasesList {...props} />
        </Suspense>
      </>
    );
  } catch (error) {
    if (error instanceof NotFoundError) notFound();
    throw error;
  }
}
