"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo } from "react";

import { formatCost, formatDate, formatDuration, refKey, refLabel } from "@/lib/format";
import { t, type Locale } from "@/lib/i18n";
import {
  DEFAULT_STATE,
  applyState,
  parseQuery,
  toQuery,
  withFilter,
  type ListState,
  type SortKey,
} from "@/lib/url-state";
import type { RunIndexEntry } from "@/lib/types";

import { DataTable, type Column } from "./DataTable";
import { FilterBar } from "./FilterBar";
import { Pagination } from "./Pagination";
import { StatusBadge, badgeFor } from "./StatusBadge";

export interface RunsListViewProps {
  locale: Locale;
  runs: RunIndexEntry[];
  /** The URL query (without `?`); empty = the default view that the static HTML shows. */
  query: string;
}

/** Workload cell: `workload`, then `· b<k>` for a nightly block and `· subset` for a judged subset (UI13-19). */
export function workloadCell(run: RunIndexEntry, locale: Locale): string {
  const block = run.block == null ? "" : ` · ${t(locale, "runs.block_short", { k: run.block })}`;
  const subset = run.judged_subset === true ? ` · ${t(locale, "runs.judged_subset_short")}` : "";
  return `${run.workload}${block}${subset}`;
}

/** Flags as text, never icons only (ui-spec §4.1). */
export function flagsOf(run: RunIndexEntry, locale: Locale): string[] {
  const flags: string[] = [];
  if (!run.complete) flags.push(t(locale, "flag.incomplete"));
  if (run.judge_mode === "skipped") flags.push(t(locale, "flag.judge_skipped"));
  if (run.judge_fallback) flags.push(t(locale, "flag.judge_fallback"));
  if (run.judge_degraded) flags.push(t(locale, "flag.judge_degraded"));
  if (run.judge_drift) flags.push(t(locale, "flag.judge_drift"));
  return flags;
}

function columns(locale: Locale): Column<RunIndexEntry>[] {
  const col = (k: string) => t(locale, `runs.col.${k}`);
  return [
    {
      id: "status",
      header: col("status"),
      sortKey: "status",
      render: (r) => <StatusBadge status={badgeFor(r)} size="sm" />,
    },
    {
      id: "ref",
      header: col("ref"),
      render: (r) => (
        <Link href={`/${locale}/runs/${r.run_id}/`} className="mono">
          {refLabel(r)}
        </Link>
      ),
    },
    {
      id: "pr",
      header: col("pr"),
      render: (r) => (r.pr_number == null ? "–" : `#${String(r.pr_number)}`),
    },
    {
      id: "created",
      header: col("created"),
      sortKey: "created",
      render: (r) => <time dateTime={r.created_at}>{formatDate(r.created_at, locale)}</time>,
    },
    {
      id: "tier",
      header: col("tier"),
      help: t(locale, "runs.tier_help"),
      render: (r) => (r.stack === "live" ? "1" : "2"),
    },
    { id: "workload", header: col("workload"), render: (r) => workloadCell(r, locale) },
    { id: "cases", header: col("cases"), numeric: true, render: (r) => r.n_cases },
    {
      id: "duration",
      header: col("duration"),
      sortKey: "duration",
      numeric: true,
      render: (r) => formatDuration(r.duration_s),
    },
    {
      id: "cost",
      header: col("cost"),
      sortKey: "cost",
      numeric: true,
      render: (r) => formatCost(r.cost_usd, locale),
    },
    { id: "flags", header: col("flags"), render: (r) => flagsOf(r, locale).join(", ") },
  ];
}

function Card({ run, locale }: { run: RunIndexEntry; locale: Locale }) {
  const flags = flagsOf(run, locale);
  return (
    <>
      <div className="card__head">
        <StatusBadge status={badgeFor(run)} size="sm" />
        <Link href={`/${locale}/runs/${run.run_id}/`} className="mono">
          {refLabel(run)}
        </Link>
      </div>
      <p>
        {formatDate(run.created_at, locale)} · {t(locale, "runs.col.tier")}{" "}
        {run.stack === "live" ? "1" : "2"} · {workloadCell(run, locale)} · {run.n_cases} ·{" "}
        {formatDuration(run.duration_s)}
      </p>
      {flags.length === 0 ? null : <p className="card__flags">{flags.join(", ")}</p>}
    </>
  );
}

/**
 * The runs list for one URL state (ui-spec §4.1). Rendered with an empty query it is the static default view
 * (page 1, created desc), which is also the `<Suspense>` fallback; after hydration the query is applied.
 */
export function RunsListView({ locale, runs, query }: RunsListViewProps) {
  const router = useRouter();
  const pathname = usePathname();
  const state = useMemo(() => parseQuery(query), [query]);
  const view = useMemo(() => applyState(runs, state), [runs, state]);
  const refs = useMemo(() => [...new Set(runs.map(refKey))].sort(), [runs]);
  const hrefFor = (next: ListState) => {
    const q = toQuery(next);
    return q === "" ? pathname : `${pathname}?${q}`;
  };
  const go = (next: ListState) => {
    router.replace(hrefFor(next), { scroll: false });
  };
  const onSort = (key: string) => {
    const same = state.sort === key;
    const dir = same && state.dir === "desc" ? "asc" : "desc";
    go({ ...state, sort: key as SortKey, dir, page: 1 });
  };
  const sortLabel = `${t(locale, `sort.${state.sort}`)} ${state.dir === "desc" ? "↓" : "↑"}`;
  const count = t(locale, "filter.count", { n: view.total });
  return (
    <>
      <h1>{t(locale, "runs.title")}</h1>
      <FilterBar
        locale={locale}
        state={state}
        refs={refs}
        count={count}
        onChange={(patch) => go(withFilter(state, patch))}
      />
      {view.total === 0 ? (
        <section className="panel" data-state="L-FILTERED-EMPTY">
          <p>{t(locale, "empty.filtered")}</p>
          <div className="panel__actions">
            <button type="button" className="btn" onClick={() => go(DEFAULT_STATE)}>
              {t(locale, "filter.clear")}
            </button>
          </div>
        </section>
      ) : (
        <section data-state="L-POPULATED">
          <p className="list-showing">
            {t(locale, "runs.showing", {
              from: view.from,
              to: view.to,
              total: view.total,
              sort: sortLabel,
            })}
          </p>
          <DataTable
            label={t(locale, "runs.title")}
            columns={columns(locale)}
            rows={view.rows}
            rowKey={(r) => r.run_id}
            card={(r) => <Card run={r} locale={locale} />}
            sort={{ key: state.sort, dir: state.dir }}
            onSort={onSort}
          />
          <Pagination
            locale={locale}
            page={view.page}
            pages={view.pages}
            hrefFor={(n) => hrefFor({ ...state, page: n })}
          />
        </section>
      )}
    </>
  );
}
