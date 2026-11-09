import { useEffect, useState } from "react";

import type { CasesState, Facet } from "@/lib/cases-state";
import { t, type Locale } from "@/lib/i18n";

export interface CaseFiltersProps {
  locale: Locale;
  state: CasesState;
  facets: Record<Facet, string[]>;
  onChange: (patch: Partial<Omit<CasesState, "page">>) => void;
}

const FACETS: Facet[] = ["tenant", "category", "lang", "perturbation"];

/** "Failing only", the four facet selects and the search box (ui-spec §4.5.2); every change goes to the URL. */
export function CaseFilters({ locale, state, facets, onChange }: CaseFiltersProps) {
  // The box keeps its own text so typing is never overwritten while the URL catches up.
  const [q, setQ] = useState(state.q);
  useEffect(() => setQ(state.q), [state.q]);
  return (
    <div className="filter-bar__controls case-filters">
      <label className="filter filter--search">
        <span>{t(locale, "cases.search")}</span>
        <input
          type="search"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            onChange({ q: e.target.value });
          }}
        />
      </label>
      <label className="filter filter--check">
        <input
          type="checkbox"
          checked={state.failing}
          onChange={(e) => onChange({ failing: e.target.checked })}
        />
        <span>{t(locale, "cases.failing_only")}</span>
      </label>
      {FACETS.map((facet) => (
        <label key={facet} className="filter">
          <span>{t(locale, `filter.${facet}`)}</span>
          <select value={state[facet]} onChange={(e) => onChange({ [facet]: e.target.value })}>
            <option value="">{t(locale, "filter.all")}</option>
            {facets[facet].map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
      ))}
    </div>
  );
}
