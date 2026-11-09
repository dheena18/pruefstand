"use client";

import { usePathname, useRouter } from "next/navigation";
import { useMemo } from "react";

import { metricLabel } from "@/lib/labels";
import { t, type Locale } from "@/lib/i18n";
import {
  dimensionsOf,
  metricsOf,
  parseSlicesQuery,
  sectionsFor,
  toSlicesQuery,
  type Section,
  type SectionId,
  type SectionState,
  type SlicesState,
} from "@/lib/slices";
import type { Stack } from "@/lib/tables";
import type { DashboardSliceRow, LabelsDocument } from "@/lib/types";

import { EmptyState } from "./EmptyState";
import { SliceChart } from "./SliceChart";
import { Tier1Notice } from "./Tier1Notice";

export interface SlicesViewProps {
  locale: Locale;
  labels: LabelsDocument;
  rows: DashboardSliceRow[];
  stack: Stack;
  /** Set for a tier-1 run (notice data). */
  tier1: { splits: string[]; n: number } | null;
  /** The URL query (without `?`); empty = the static default view. */
  query: string;
}

function title(locale: Locale, id: SectionId, tier1: SlicesViewProps["tier1"]): string {
  if (id === "checks") return t(locale, "tier1.checks");
  if (id === "reported") return t(locale, "tier1.reported", { n: tier1?.n ?? "" });
  return t(locale, id === "gated" ? "slices.gated" : "slices.informational");
}

function Selectors({
  locale,
  labels,
  section,
  state,
  onChange,
}: {
  locale: Locale;
  labels: LabelsDocument;
  section: Section;
  state: SectionState;
  onChange: (next: SectionState) => void;
}) {
  const uid = `sel-${section.id}`;
  return (
    <div className="filter-bar__controls slice-controls">
      <label className="filter" htmlFor={`${uid}-d`}>
        <span>{t(locale, "slices.dimension")}</span>
        <select
          id={`${uid}-d`}
          value={state.dimension}
          onChange={(e) => onChange({ dimension: e.target.value, metric: "" })}
        >
          {dimensionsOf(section.rows).map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </label>
      <label className="filter" htmlFor={`${uid}-m`}>
        <span>{t(locale, "slices.metric")}</span>
        <select
          id={`${uid}-m`}
          value={state.metric}
          onChange={(e) => onChange({ ...state, metric: e.target.value })}
        >
          <option value="">{t(locale, "slices.all_metrics")}</option>
          {metricsOf(section.rows, state.dimension).map((m) => (
            <option key={m} value={m}>
              {metricLabel(locale, labels, m)}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function SectionBody({
  locale,
  labels,
  section,
  state,
}: {
  locale: Locale;
  labels: LabelsDocument;
  section: Section;
  state: SectionState;
}) {
  const metrics = state.metric === "" ? metricsOf(section.rows, state.dimension) : [state.metric];
  if (metrics.length === 0) return <p className="slices-empty">{t(locale, "empty.slices")}</p>;
  return (
    <>
      {metrics.map((metric) => (
        <SliceChart
          key={metric}
          locale={locale}
          labels={labels}
          rows={section.rows}
          dimension={state.dimension}
          metric={metric}
          group={section.id}
        />
      ))}
    </>
  );
}

/**
 * The Slices page body (ui-spec §4.4): the sections of `sectionsFor` (Gated / Informational, or in tier 1
 * Checks / Reported / Informational), each with its own dimension and metric choice in the URL.
 */
export function SlicesView({ locale, labels, rows, stack, tier1, query }: SlicesViewProps) {
  const router = useRouter();
  const pathname = usePathname();
  const sections = useMemo(() => sectionsFor(rows, stack), [rows, stack]);
  const state = useMemo(() => parseSlicesQuery(query, sections), [query, sections]);
  const change = (id: SectionId, next: SectionState) => {
    const q = toSlicesQuery({ ...state, [id]: next } as SlicesState, sections);
    router.replace(q === "" ? pathname : `${pathname}?${q}`, { scroll: false });
  };
  return (
    <div>
      <h1>{t(locale, "subnav.slices")}</h1>
      {tier1 === null ? null : <Tier1Notice locale={locale} splits={tier1.splits} n={tier1.n} />}
      {sections.length === 0 ? <EmptyState title={t(locale, "empty.slices")} /> : null}
      {sections.map((section) => {
        const current = state[section.id] ?? { dimension: "overall", metric: "" };
        return (
          <section
            key={section.id}
            data-section={section.id}
            className="slices-section"
            aria-labelledby={`h-${section.id}`}
          >
            <h2 id={`h-${section.id}`}>{title(locale, section.id, tier1)}</h2>
            <Selectors
              locale={locale}
              labels={labels}
              section={section}
              state={current}
              onChange={(next) => change(section.id, next)}
            />
            <SectionBody locale={locale} labels={labels} section={section} state={current} />
          </section>
        );
      })}
    </div>
  );
}
