import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { RunPageHead } from "@/components/RunPageHead";
import { RunsPlaceholder } from "@/components/RunsPlaceholder";
import { SlicesQuery } from "@/components/SlicesQuery";
import { SlicesView } from "@/components/SlicesView";
import { loadSlices } from "@/lib/data";
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
    title: `Prüfstand · ${ctx === null ? id : refLabel(ctx.run)} · Slices`,
    alternates: alternatesFor(`runs/${id}/slices`),
  };
}

/** Slices (ui-spec §4.4): gated vs informational slice charts of one run. */
export default async function SlicesPage({ params }: { params: Params }) {
  const { locale, id } = await params;
  if (!isLocale(locale)) notFound();
  if (id === EMPTY_ID) return <RunsPlaceholder locale={locale} />;
  try {
    const ctx = await loadRunContext(id);
    if (ctx.gate === null || ctx.gate.no_baseline === true) notFound();
    const { rows } = await loadSlices(id);
    const tier1 = ctx.run.stack === "live" ? { splits: ctx.run.splits, n: ctx.run.n_cases } : null;
    const props = { locale, labels: ctx.labels, rows, stack: ctx.run.stack, tier1 };
    return (
      <>
        <RunPageHead locale={locale} ctx={ctx} active="slices" />
        <Suspense fallback={<SlicesView {...props} query="" />}>
          <SlicesQuery {...props} />
        </Suspense>
      </>
    );
  } catch (error) {
    if (error instanceof NotFoundError) notFound();
    throw error;
  }
}
