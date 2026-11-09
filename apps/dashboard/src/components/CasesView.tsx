"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo } from "react";

import { mergedRows, summarize } from "@/lib/cases";
import {
  applyCases,
  facetValues,
  parseCasesQuery,
  toCasesQuery,
  withCasesFilter,
  type CasesState,
  type Facet,
} from "@/lib/cases-state";
import { isSafeId } from "@/lib/ids";
import { t, type Locale } from "@/lib/i18n";
import type { DashboardCase, HardFailFinding, LabelsDocument } from "@/lib/types";
import { useShards } from "@/lib/use-shards";

import { CaseDetailPanel } from "./CaseDetailPanel";
import { CaseFilters } from "./CaseFilters";
import { CaseListItem } from "./CaseListItem";
import { Pagination } from "./Pagination";
import { ShardStatus } from "./ShardStatus";
import { Skeleton } from "./Skeleton";

export interface CasesViewProps {
  locale: Locale;
  labels: LabelsDocument;
  runId: string;
  nShards: number;
  /** Length of shard 0, read at build time. */
  shard0Length: number;
  /** `failing == true` rows of shard 0, read at build time ("n failing"; R4 puts every failing case there). */
  failingCount: number;
  /** Page 1 of the default view, from shard 0 at build time: the static HTML and what shows until shard 0 arrives. */
  staticRows: DashboardCase[];
  hardFails: HardFailFinding[];
  /** The baseline run, when its case shards are exported; otherwise null → "Baseline not exported". */
  baseline: { runId: string; nShards: number } | null;
  /** The URL query (without `?`); empty = the static default view. */
  query: string;
  /** False for the static fallback: nothing is fetched. */
  live: boolean;
}

const FACETS: Facet[] = ["tenant", "category", "lang", "perturbation"];

function Detail({
  p,
  rows,
  settled,
  state,
  hrefFor,
}: {
  p: CasesViewProps;
  rows: DashboardCase[];
  settled: boolean;
  state: CasesState;
  hrefFor: (next: CasesState) => string;
}) {
  const value = rows.find((c) => c.case_id === state.case);
  if (value !== undefined) {
    const pageHref =
      value.failing && isSafeId(value.case_id)
        ? `/${p.locale}/runs/${p.runId}/cases/${value.case_id}/`
        : null;
    return (
      <CaseDetailPanel
        locale={p.locale}
        labels={p.labels}
        value={value}
        hardFails={p.hardFails}
        baseline={p.baseline}
        pageHref={pageHref}
        backHref={hrefFor({ ...state, case: "" })}
      />
    );
  }
  if (!settled) return <Skeleton shape="block" />;
  return (
    <section className="panel panel--inline" data-state="C-NOT-FOUND">
      <p>{t(p.locale, "case.not_found", { id: state.case })}</p>
      <Link href={hrefFor({ ...state, case: "" })}>{t(p.locale, "cases.back")}</Link>
    </section>
  );
}

/**
 * The cases list (ui-spec §4.5.2): filter, search and pagination over the loaded shards, all in the URL; the detail
 * panel beside the list (≥ 1024 px) or instead of it. Until shard 0 arrives it shows the build-time rows.
 */
export function CasesView(p: CasesViewProps) {
  const { locale, runId, nShards, query, live } = p;
  const router = useRouter();
  const pathname = usePathname();
  const { state: shards, retry } = useShards(runId, nShards, live);
  const hasFailing = p.failingCount > 0;
  const state = useMemo(() => parseCasesQuery(query, hasFailing), [query, hasFailing]);
  const haveShard0 = shards.shards[0] !== undefined;
  const rows = useMemo(
    () => (haveShard0 ? mergedRows(shards) : p.staticRows),
    [haveShard0, shards, p.staticRows],
  );
  const sum = summarize(shards);
  const total = haveShard0 ? sum.total : p.shard0Length;
  const loaded = haveShard0 ? sum.loaded : 1; // the build-time copy of shard 0 counts as part 1
  const view = useMemo(() => applyCases(rows, state), [rows, state]);
  const facets = useMemo(
    () =>
      Object.fromEntries(FACETS.map((f) => [f, facetValues(rows, f)])) as Record<Facet, string[]>,
    [rows],
  );
  const hrefFor = (next: CasesState) => {
    const q = toCasesQuery(next, hasFailing);
    return q === "" ? pathname : `${pathname}?${q}`;
  };
  const go = (next: CasesState) => router.replace(hrefFor(next), { scroll: false });
  const settled = shards.loaded + shards.failed.length >= nShards;
  return (
    <div className={`cases${state.case === "" ? "" : " cases--detail"}`}>
      <div className="cases-head">
        <h1>
          {t(locale, "cases.title", { total })}
          {loaded < nShards ? ` ${t(locale, "cases.partial")}` : ""}
        </h1>
        <p>{t(locale, "cases.failing", { n: p.failingCount })}</p>
      </div>
      {live ? (
        <ShardStatus
          locale={locale}
          nShards={nShards}
          loaded={loaded}
          failed={shards.failed}
          onRetry={retry}
        />
      ) : null}
      <CaseFilters
        locale={locale}
        state={state}
        facets={facets}
        onChange={(patch) => go(withCasesFilter(state, patch))}
      />
      <div className="cases-layout">
        <div className="cases-list">
          {view.total === 0 ? (
            <section className="panel panel--inline" data-state="L-FILTERED-EMPTY">
              <p>{t(locale, "empty.cases")}</p>
            </section>
          ) : (
            <>
              <ul
                className="case-items"
                aria-label={t(locale, "cases.title", { total: view.total })}
              >
                {view.rows.map((c) => (
                  <CaseListItem
                    key={c.case_id}
                    locale={locale}
                    value={c}
                    selected={c.case_id === state.case}
                    href={hrefFor({ ...state, case: c.case_id })}
                    pageHref={
                      c.failing && isSafeId(c.case_id)
                        ? `/${locale}/runs/${runId}/cases/${c.case_id}/`
                        : null
                    }
                  />
                ))}
              </ul>
              <Pagination
                locale={locale}
                page={view.page}
                pages={view.pages}
                hrefFor={(n) => hrefFor({ ...state, page: n })}
              />
            </>
          )}
        </div>
        {state.case === "" ? null : (
          <div className="cases-detail">
            <Detail p={p} rows={rows} settled={settled && live} state={state} hrefFor={hrefFor} />
          </div>
        )}
      </div>
    </div>
  );
}
