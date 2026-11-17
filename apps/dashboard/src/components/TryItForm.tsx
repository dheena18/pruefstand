import { t, type Locale } from "@/lib/i18n";
import {
  MAX_QUESTION,
  canAsk,
  isLoading,
  validate,
  type TryAction,
  type TryState,
} from "@/lib/try-state";

export interface TryTenant {
  id: string;
  label: Record<Locale, string>;
  description: Record<Locale, string>;
}

export interface TryExample {
  tenant: string;
  question: string;
}

export interface TryItFormProps {
  locale: Locale;
  state: TryState;
  tenants: readonly TryTenant[];
  examples: readonly TryExample[];
  dispatch: (action: TryAction) => void;
  onSubmit: () => void;
  onCancel: () => void;
}

/** Tenant choice, German question field, examples and the Ask / Cancel buttons (ui-spec §4.6). */
export function TryItForm({
  locale,
  state,
  tenants,
  examples,
  dispatch,
  onSubmit,
  onCancel,
}: TryItFormProps) {
  const loading = isLoading(state.id);
  const problem = state.touched ? validate(state.question) : null;
  return (
    <form
      className="try-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <p>{t(locale, "try.intro")}</p>
      <fieldset disabled={loading}>
        <legend>{t(locale, "try.tenant")}</legend>
        {tenants.map((tenant) => (
          <label key={tenant.id} className="try-tenant">
            <input
              type="radio"
              name="tenant"
              value={tenant.id}
              checked={state.tenant === tenant.id}
              onChange={() => dispatch({ type: "tenant", tenant: tenant.id })}
            />{" "}
            {tenant.label[locale]} — {tenant.description[locale]}
          </label>
        ))}
      </fieldset>
      <label htmlFor="try-question">{t(locale, "try.question")}</label>
      <textarea
        id="try-question"
        lang="de"
        rows={3}
        maxLength={MAX_QUESTION}
        value={state.question}
        readOnly={loading}
        aria-invalid={problem !== null}
        aria-describedby={problem === null ? "try-count" : "try-count try-problem"}
        onChange={(event) => dispatch({ type: "input", question: event.target.value })}
      />
      <p
        id="try-count"
        className={
          state.question.length >= MAX_QUESTION ? "try-count try-count--full" : "try-count"
        }
      >
        {state.question.length} / {MAX_QUESTION}
      </p>
      {problem === null ? null : (
        <p id="try-problem" className="try-problem">
          {t(locale, `try.invalid.${problem}`)}
        </p>
      )}
      <p>
        {t(locale, "try.examples")}{" "}
        {examples.map((example) => (
          <button
            key={example.question}
            type="button"
            className="btn btn--small"
            lang="de"
            disabled={loading}
            onClick={() => {
              dispatch({ type: "tenant", tenant: example.tenant });
              dispatch({ type: "input", question: example.question });
            }}
          >
            {example.question}
          </button>
        ))}
      </p>
      <p>
        <button type="submit" className="btn btn--primary" disabled={!canAsk(state)}>
          {loading ? t(locale, "try.asking") : t(locale, "try.ask")}
        </button>{" "}
        {loading ? (
          <button type="button" className="btn" onClick={onCancel}>
            {t(locale, "try.cancel")}
          </button>
        ) : null}
        {state.id === "T-SLOW" ? <span className="try-slow">{t(locale, "try.slow")}</span> : null}
        {loading ? (
          <span className="try-elapsed">{t(locale, "try.elapsed", { s: state.elapsedS })}</span>
        ) : null}
      </p>
      <p>{t(locale, "try.hint")}</p>
      <p>{t(locale, "try.limits")}</p>
    </form>
  );
}
