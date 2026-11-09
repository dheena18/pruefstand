"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { t, type Locale } from "@/lib/i18n";
import { useBaselineCase } from "@/lib/use-shards";
import type { DashboardCase, HardFailFinding, LabelsDocument } from "@/lib/types";

import { CaseDetail } from "./CaseDetail";

export interface CaseDetailPanelProps {
  locale: Locale;
  labels: LabelsDocument;
  value: DashboardCase;
  hardFails: HardFailFinding[];
  baseline: { runId: string; nShards: number } | null;
  pageHref: string | null;
  /** Href of the list without the selected case ("Back to cases", shown below 1024 px). */
  backHref: string;
}

/** Below 1024 px the panel replaces the list, so a selection moves focus to the detail heading (ui-spec §4.5.2). */
const narrow = (): boolean =>
  typeof window.matchMedia === "function" && window.matchMedia("(max-width: 1023px)").matches;

/** The list's detail panel: `CaseDetail` plus the baseline lookup, the copy-link button and the back link. */
export function CaseDetailPanel({
  locale,
  labels,
  value,
  hardFails,
  baseline,
  pageHref,
  backHref,
}: CaseDetailPanelProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [copied, setCopied] = useState(false);
  const baselineState = useBaselineCase(baseline, value.case_id);
  useEffect(() => {
    if (narrow()) heading.current?.focus();
    setCopied(false);
  }, [value.case_id]);
  const copy = () => {
    void navigator.clipboard?.writeText(window.location.href).then(() => setCopied(true));
  };
  return (
    <div className="cases-detail__panel">
      <Link href={backHref} className="cases-back">
        ← {t(locale, "cases.back")}
      </Link>
      <CaseDetail
        locale={locale}
        labels={labels}
        value={value}
        baseline={baselineState}
        hardFails={hardFails.filter((f) => f.case_id === value.case_id)}
        pageHref={pageHref}
        headingRef={heading}
        actions={
          <button type="button" className="btn" onClick={copy}>
            {copied ? t(locale, "cases.copied") : t(locale, "cases.copy_link")}
          </button>
        }
      />
    </div>
  );
}
