import Link from "next/link";
import type { ReactNode } from "react";

import { refLabel } from "@/lib/format";
import { t, type Locale } from "@/lib/i18n";
import type { RunContext } from "@/lib/run-context";

import { RunSubNav } from "./RunSubNav";

export interface Crumb {
  label: ReactNode;
  href?: string;
}

export interface RunPageHeadProps {
  locale: Locale;
  ctx: RunContext;
  active: "diff" | "slices" | "cases";
  /** Crumbs after the run (e.g. `Cases › law-0107`). */
  trail?: Crumb[];
}

/** Breadcrumb `Runs › <run> › …` and the run sub-nav shared by Diff, Slices, Cases and the case pages. */
export function RunPageHead({ locale, ctx, active, trail = [] }: RunPageHeadProps) {
  const { run, gate, casesPublished, failing } = ctx;
  return (
    <>
      <nav aria-label="breadcrumb" className="breadcrumb">
        <Link href={`/${locale}/`}>{t(locale, "nav.runs")}</Link> ›{" "}
        <Link href={`/${locale}/runs/${run.run_id}/`} className="mono">
          {refLabel(run)}
        </Link>
        {trail.map((crumb, i) => (
          <span key={i}>
            {" "}
            ›{" "}
            {crumb.href === undefined ? (
              <span className="mono">{crumb.label}</span>
            ) : (
              <Link href={crumb.href}>{crumb.label}</Link>
            )}
          </span>
        ))}
      </nav>
      <RunSubNav
        locale={locale}
        runId={run.run_id}
        active={active}
        failing={failing}
        gated={gate !== null}
        noBaseline={gate?.no_baseline === true}
        casesPublished={casesPublished}
      />
    </>
  );
}
