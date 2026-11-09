import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CaseDetail } from "@/components/CaseDetail";
import { EmptyState } from "@/components/EmptyState";
import { RunPageHead } from "@/components/RunPageHead";
import { baselineCaseAtBuild } from "@/lib/case-page";
import { NotFoundError } from "@/lib/errors";
import { refLabel } from "@/lib/format";
import { LOCALES, isLocale, t } from "@/lib/i18n";
import { EMPTY_ID, isSafeId } from "@/lib/ids";
import { alternatesFor } from "@/lib/paths";
import { loadRunContext } from "@/lib/run-context";
import { casePublishedRunIds, shardZero } from "@/lib/run-pages";

export const dynamicParams = false;

type Params = Promise<{ locale: string; id: string; caseId: string }>;

/**
 * `{id, caseId}` of the failing cases of every run with published shards (ui-spec §4.5.3). A published run without
 * a failing case gets `{id, caseId: "_empty"}`; no published run at all gets `{id: "_empty", caseId: "_empty"}`.
 */
export async function generateStaticParams() {
  const out: { id: string; caseId: string }[] = [];
  for (const id of await casePublishedRunIds()) {
    const failing = ((await shardZero(id))?.cases ?? []).filter(
      (c) => c.failing && isSafeId(c.case_id),
    );
    if (failing.length === 0) out.push({ id, caseId: EMPTY_ID });
    for (const c of failing) out.push({ id, caseId: c.case_id });
  }
  const items = out.length === 0 ? [{ id: EMPTY_ID, caseId: EMPTY_ID }] : out;
  return LOCALES.flatMap((locale) => items.map((item) => ({ locale, ...item })));
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { id, caseId } = await params;
  if (id === EMPTY_ID || caseId === EMPTY_ID)
    return { robots: { index: false }, title: "Prüfstand" };
  const ctx = await loadRunContext(id).catch(() => null);
  return {
    title: `Prüfstand · ${ctx === null ? id : refLabel(ctx.run)} · ${caseId}`,
    alternates: alternatesFor(`runs/${id}/cases/${caseId}`),
  };
}

/** Static page of one failing case (ui-spec §4.5.3): the same `CaseDetail` as the list's panel, full width. */
export default async function CasePage({ params }: { params: Params }) {
  const { locale, id, caseId } = await params;
  if (!isLocale(locale)) notFound();
  if (caseId === EMPTY_ID) {
    const href = id === EMPTY_ID ? `/${locale}/` : `/${locale}/runs/${id}/cases/`;
    return (
      <EmptyState
        title={t(locale, "empty.cases")}
        action={{ href, label: t(locale, id === EMPTY_ID ? "nav.runs" : "cases.back") }}
      />
    );
  }
  try {
    const ctx = await loadRunContext(id);
    const value = (await shardZero(id))?.cases.find((c) => c.case_id === caseId);
    if (value === undefined) notFound();
    const base = `/${locale}/runs/${id}/`;
    return (
      <>
        <RunPageHead
          locale={locale}
          ctx={ctx}
          active="cases"
          trail={[{ label: t(locale, "cases.crumb"), href: `${base}cases/` }, { label: caseId }]}
        />
        <CaseDetail
          locale={locale}
          labels={ctx.labels}
          value={value}
          baseline={await baselineCaseAtBuild(ctx, caseId)}
          hardFails={(ctx.gate?.hard_fails ?? []).filter((f) => f.case_id === caseId)}
          level={1}
        />
      </>
    );
  } catch (error) {
    if (error instanceof NotFoundError) notFound();
    throw error;
  }
}
