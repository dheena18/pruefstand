import Link from "next/link";

import { t, type Locale } from "@/lib/i18n";

export interface RunSubNavProps {
  locale: Locale;
  runId: string;
  active: "summary" | "diff" | "slices" | "cases";
  /** Failing rows of case shard 0, read at build time (UI9-22); never `n_cases`. */
  failing: number;
  /** The run has a `gate.json`. */
  gated: boolean;
  noBaseline: boolean;
  /** `cases/<id>/0.json` exists; false → `S-CASES-PRUNED`. */
  casesPublished: boolean;
}

function Item({
  href,
  label,
  active,
  note,
}: {
  href: string;
  label: string;
  active: boolean;
  note: string | null;
}) {
  if (note !== null) {
    return (
      <span aria-disabled="true" className="subnav__item subnav__item--disabled">
        {label} {note}
      </span>
    );
  }
  return (
    <Link href={href} className="subnav__item" aria-current={active ? "page" : undefined}>
      {label}
    </Link>
  );
}

/** Summary | Diff | Slices | Cases (n failing). Disabled items are `aria-disabled` spans with a reason. */
export function RunSubNav(props: RunSubNavProps) {
  const { locale, runId, active, failing, gated, noBaseline, casesPublished } = props;
  const base = `/${locale}/runs/${runId}/`;
  let compareNote: string | null = null;
  if (!gated) compareNote = t(locale, "subnav.not_gated");
  else if (noBaseline) compareNote = t(locale, "subnav.nothing_compared");
  return (
    <nav className="subnav" aria-label={t(locale, "nav.run")}>
      <Item
        href={base}
        label={t(locale, "subnav.summary")}
        active={active === "summary"}
        note={null}
      />
      <Item
        href={`${base}diff/`}
        label={t(locale, "subnav.diff")}
        active={active === "diff"}
        note={compareNote}
      />
      <Item
        href={`${base}slices/`}
        label={t(locale, "subnav.slices")}
        active={active === "slices"}
        note={compareNote}
      />
      <Item
        href={`${base}cases/`}
        label={
          casesPublished
            ? t(locale, "subnav.cases", { n: failing })
            : t(locale, "subnav.cases").replace(/\s*\(.*\)$/, "")
        }
        active={active === "cases"}
        note={casesPublished ? null : t(locale, "subnav.cases_not_published")}
      />
    </nav>
  );
}
