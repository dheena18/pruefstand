import { t, type Locale } from "@/lib/i18n";
import { STATUS_VALUES, TIER_VALUES, WORKLOAD_VALUES, type ListState } from "@/lib/url-state";

export interface FilterBarProps {
  locale: Locale;
  state: ListState;
  /** Distinct ref keys of the index (`pr-62`, `main`, …). */
  refs: string[];
  onChange: (patch: Partial<Pick<ListState, "status" | "ref" | "tier" | "workload">>) => void;
  /** The count line; rendered in an `aria-live="polite"` region (filters never move focus). */
  count: string;
}

type Key = "status" | "ref" | "tier" | "workload";

function Select({
  id,
  locale,
  value,
  options,
  onChange,
}: {
  id: Key;
  locale: Locale;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="filter">
      <span>{t(locale, `filter.${id}`)}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t(locale, "filter.all")}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Status / Ref / Tier / Workload selects (ui-spec §4.1) and the live count. */
export function FilterBar({ locale, state, refs, onChange, count }: FilterBarProps) {
  const word = (v: string) => v.replaceAll("_", " ").toUpperCase();
  const set = (key: Key) => (value: string) => onChange({ [key]: value });
  return (
    <div className="filter-bar">
      <div className="filter-bar__controls">
        <Select
          id="status"
          locale={locale}
          value={state.status}
          onChange={set("status")}
          options={STATUS_VALUES.map((v) => ({ value: v, label: word(v) }))}
        />
        <Select
          id="ref"
          locale={locale}
          value={state.ref}
          onChange={set("ref")}
          options={refs.map((v) => ({ value: v, label: v }))}
        />
        <Select
          id="tier"
          locale={locale}
          value={state.tier}
          onChange={set("tier")}
          options={TIER_VALUES.map((v) => ({ value: v, label: v }))}
        />
        <Select
          id="workload"
          locale={locale}
          value={state.workload}
          onChange={set("workload")}
          options={WORKLOAD_VALUES.map((v) => ({ value: v, label: v }))}
        />
      </div>
      <p className="filter-bar__count" aria-live="polite">
        {count}
      </p>
    </div>
  );
}
