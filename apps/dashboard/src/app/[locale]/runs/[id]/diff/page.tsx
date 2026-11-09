import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { DiffQuery } from "@/components/DiffQuery";
import { DiffView } from "@/components/DiffView";
import { RunPageHead } from "@/components/RunPageHead";
import { RunsPlaceholder } from "@/components/RunsPlaceholder";
import { buildDiffModel } from "@/lib/diff";
import { NotFoundError } from "@/lib/errors";
import { refLabel } from "@/lib/format";
import { isLocale } from "@/lib/i18n";
import { EMPTY_ID } from "@/lib/ids";
import { alternatesFor } from "@/lib/paths";
import { loadRunContext } from "@/lib/run-context";
import { comparedRunIds, forLocales } from "@/lib/run-pages";

export const dynamicParams = false;

type Params = Promise<{ locale: string; id: string }>;

/** Runs with `gate.json` and `no_baseline == false`; none → the `_empty` placeholder (UI12-08). */
export async function generateStaticParams() {
  const ids = await comparedRunIds();
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
    title: `Prüfstand · ${ctx === null ? id : refLabel(ctx.run)} · Diff`,
    alternates: alternatesFor(`runs/${id}/diff`),
  };
}

/** Diff (ui-spec §4.3): the gated pairs of one run against its baseline. */
export default async function DiffPage({ params }: { params: Params }) {
  const { locale, id } = await params;
  if (!isLocale(locale)) notFound();
  if (id === EMPTY_ID) return <RunsPlaceholder locale={locale} />;
  let ctx;
  try {
    ctx = await loadRunContext(id);
  } catch (error) {
    if (error instanceof NotFoundError) notFound();
    throw error;
  }
  if (ctx.gate === null || ctx.gate.no_baseline === true) notFound();
  const props = { locale, labels: ctx.labels, model: buildDiffModel(ctx) };
  return (
    <>
      <RunPageHead locale={locale} ctx={ctx} active="diff" />
      <Suspense fallback={<DiffView {...props} query="" />}>
        <DiffQuery {...props} />
      </Suspense>
    </>
  );
}
