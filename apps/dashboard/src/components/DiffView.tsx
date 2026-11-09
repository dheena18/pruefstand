"use client";

import { usePathname, useRouter } from "next/navigation";
import { useMemo } from "react";

import {
  DIFF_SORTS,
  applyDiff,
  ciDomain,
  countRows,
  parseDiffQuery,
  sliceOptions,
  toDiffQuery,
  type DiffModel,
  type DiffState,
} from "@/lib/diff";
import { t, type Locale } from "@/lib/i18n";
import type { LabelsDocument } from "@/lib/types";

import { CiChart } from "./CiChart";
import { MetricTable } from "./MetricTable";
import { Pagination } from "./Pagination";
import { Tier1Notice } from "./Tier1Notice";

export interface DiffViewProps {
  locale: Locale;
  labels: LabelsDocument;
  model: DiffModel;
  /** The URL query (without `?`); empty = the default view that the static HTML shows (UI11-09). */
  query: string;
}

function Controls({
  locale,
  state,
  slices,
  onChange,
}: {
  locale: Locale;
  state: DiffState;
  slices: string[];
  onChange: (next: DiffState) => void;
}) {
  return (
    <div className="filter-bar__controls diff-controls">
      <label className="filter">
        <span>{t(locale, "sort.label")}</span>
        <select
          value={state.sort}
          onChange={(e) =>
            onChange({ ...state, sort: e.target.value as DiffState["sort"], page: 1 })
          }
        >
          {DIFF_SORTS.map((s) => (
            <option key={s} value={s}>
              {t(locale, `sort.${s}`)}
            </option>
          ))}
        </select>
      </label>
      <label className="filter">
        <span>{t(locale, "filter.slice")}</span>
        <select
          value={state.slice}
          onChange={(e) => onChange({ ...state, slice: e.target.value, page: 1 })}
        >
          <option value="">{t(locale, "filter.all")}</option>
          {slices.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

/**
 * The Diff page body (ui-spec §4.3). Tier 2: one dot-and-whisker row per block-G pair on a shared scale, sort and
 * slice filter in the URL. Tier 1: `Tier1Notice` and the reported block R, no chart. Rendered with an empty query
 * it is the static default view and the `<Suspense>` fallback of the query reader.
 */
export function DiffView({ locale, labels, model, query }: DiffViewProps) {
  const router = useRouter();
  const pathname = usePathname();
  const state = useMemo(() => parseDiffQuery(query), [query]);
  const view = useMemo(() => applyDiff(model.rows, state), [model.rows, state]);
  const domain = useMemo(() => ciDomain(model.rows), [model.rows]);
  const hrefFor = (next: DiffState) => {
    const q = toDiffQuery(next);
    return q === "" ? pathname : `${pathname}?${q}`;
  };
  if (model.tier1 !== null) {
    const { splits, n } = model.tier1;
    return (
      <div data-state="S-TIER1">
        <h1>{t(locale, "subnav.diff")}</h1>
        <Tier1Notice locale={locale} splits={splits} n={n} />
        <MetricTable
          locale={locale}
          labels={labels}
          rows={model.reported}
          variant="reported"
          caption={t(locale, "tier1.reported", { n })}
        />
      </div>
    );
  }
  if (model.rows.length === 0) {
    return (
      <div>
        <h1>{t(locale, "subnav.diff")}</h1>
        <p>{t(locale, "diff.empty")}</p>
      </div>
    );
  }
  return (
    <div>
      <h1>{t(locale, "diff.title", countRows(model.rows))}</h1>
      <Controls
        locale={locale}
        state={state}
        slices={sliceOptions(model.rows)}
        onChange={(next) => router.replace(hrefFor(next), { scroll: false })}
      />
      <CiChart locale={locale} labels={labels} rows={view.rows} domain={domain} />
      <Pagination
        locale={locale}
        page={view.page}
        pages={view.pages}
        hrefFor={(n) => hrefFor({ ...state, page: n })}
      />
    </div>
  );
}
