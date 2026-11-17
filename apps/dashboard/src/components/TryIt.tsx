"use client";

import { useEffect, useReducer, useRef } from "react";

import { t, type Locale } from "@/lib/i18n";
import { ask } from "@/lib/try-api";
import { canAsk, initialState, isLoading, reduce, type TryStateId } from "@/lib/try-state";

import { AnswerCard } from "./AnswerCard";
import { RetryCountdown } from "./RetryCountdown";
import { TryItForm, type TryExample, type TryTenant } from "./TryItForm";

export interface TryItProps {
  locale: Locale;
  apiUrl: string;
  timeoutS: number;
  tenants: readonly TryTenant[];
  examples: readonly TryExample[];
}

const ERROR_KEYS: Partial<Record<TryStateId, string>> = {
  "T-RATE-LIMITED": "try.error.rate_limited",
  "T-BUSY": "try.error.busy",
  "T-DAILY-LIMIT": "try.error.daily_limit",
  "T-BUDGET": "try.error.budget",
  "T-DEMO-OFF": "try.error.disabled",
  "T-REJECTED": "try.error.rejected",
  "T-NETWORK": "try.error.network",
  "T-SERVER-ERROR": "try.error.server",
  "T-TIMEOUT": "try.error.timeout",
};
const RETRYABLE = new Set<TryStateId>(["T-NETWORK", "T-SERVER-ERROR", "T-TIMEOUT"]);

/** The Try-it page: owns the reducer, the timers and the one `fetch` (ui-spec §4.6). */
export function TryIt({ locale, apiUrl, timeoutS, tenants, examples }: TryItProps) {
  const [state, dispatch] = useReducer(reduce, tenants[0]?.id ?? "", initialState);
  const abort = useRef<AbortController | null>(null);
  const initialCountdown = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const loading = isLoading(state.id);

  useEffect(() => {
    if (!loading) return;
    const timer = setInterval(() => dispatch({ type: "tick" }), 1000);
    return () => clearInterval(timer);
  }, [loading]);

  const counting = state.countdownS !== null && state.countdownS > 0;
  useEffect(() => {
    if (!counting) return;
    const timer = setInterval(() => dispatch({ type: "countdown" }), 1000);
    return () => clearInterval(timer);
  }, [counting]);

  useEffect(() => {
    if (state.id === "T-SUCCESS" || state.id === "T-REFUSED") heading.current?.focus();
  }, [state.id]);

  const submit = () => {
    if (!canAsk(state)) {
      dispatch({ type: "submit" });
      return;
    }
    dispatch({ type: "submit" });
    const controller = new AbortController();
    abort.current = controller;
    const deadline = setTimeout(() => {
      controller.abort();
      dispatch({ type: "client_timeout" });
    }, timeoutS * 1000);
    void ask(apiUrl, state.tenant, state.question, controller.signal).then((outcome) => {
      clearTimeout(deadline);
      if (outcome.kind === "ok") dispatch({ type: "answered", answer: outcome.answer });
      if (outcome.kind === "failure") {
        initialCountdown.current = outcome.failure.retryAfterS ?? 0;
        dispatch({ type: "failed", failure: outcome.failure });
      }
    });
  };
  const cancel = () => {
    abort.current?.abort();
    dispatch({ type: "cancel" });
  };

  const errorKey = ERROR_KEYS[state.id];
  const withCountdown = state.id === "T-RATE-LIMITED" || state.id === "T-BUSY";
  return (
    <div data-state={state.id}>
      <p className="sr-only" aria-live="polite">
        {state.id === "T-CANCELLED"
          ? t(locale, "try.cancelled")
          : loading
            ? t(locale, "try.asking")
            : ""}
      </p>
      <TryItForm
        locale={locale}
        state={state}
        tenants={tenants}
        examples={examples}
        dispatch={dispatch}
        onSubmit={submit}
        onCancel={cancel}
      />
      {errorKey === undefined ? null : withCountdown && state.countdownS !== null ? (
        <RetryCountdown
          locale={locale}
          messageKey={errorKey}
          initialS={initialCountdown.current}
          remainingS={state.countdownS}
        />
      ) : (
        <div className="panel panel--error panel--inline" role="alert">
          <p>{t(locale, errorKey, { s: 0 })}</p>
          {RETRYABLE.has(state.id) ? (
            <button type="button" className="btn" onClick={submit}>
              {t(locale, "try.retry")}
            </button>
          ) : null}
        </div>
      )}
      {state.answer === null ? null : (
        <AnswerCard
          locale={locale}
          answer={state.answer}
          elapsedS={state.elapsedS}
          tenant={state.tenant}
          headingRef={heading}
        />
      )}
    </div>
  );
}
