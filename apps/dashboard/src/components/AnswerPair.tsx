import type { BaselineState } from "@/lib/cases";
import { t, type Locale } from "@/lib/i18n";
import type { DashboardCase } from "@/lib/types";

import { Skeleton } from "./Skeleton";

export type { BaselineState };

function Answer({
  locale,
  value,
  heading,
}: {
  locale: Locale;
  value: DashboardCase;
  heading: string;
}) {
  return (
    <section aria-label={heading} className="answer">
      <h3>
        {heading}
        {value.refused === true ? (
          <span className="badge badge--neutral badge--sm">{t(locale, "case.refused")}</span>
        ) : null}
      </h3>
      {value.error != null ? (
        <p className="case-error">{t(locale, "case.error", { class: value.error })}</p>
      ) : value.answer == null ? (
        <p className="muted">{t(locale, "case.no_answer")}</p>
      ) : (
        <p lang={value.lang} className="case-text pre-wrap">
          {value.answer}
        </p>
      )}
    </section>
  );
}

function BaselineSide({ locale, baseline }: { locale: Locale; baseline: BaselineState }) {
  const heading = t(locale, "case.baseline_answer");
  if (baseline.state === "found")
    return <Answer locale={locale} value={baseline.value} heading={heading} />;
  const body =
    baseline.state === "loading" ? (
      <Skeleton shape="block" />
    ) : baseline.state === "error" ? (
      <p role="status">{t(locale, "case.baseline_error")}</p>
    ) : (
      <p>{t(locale, "case.baseline_missing")}</p>
    );
  return (
    <section
      aria-label={heading}
      className="answer answer--missing"
      data-state={baseline.state === "missing" ? "baseline-missing" : baseline.state}
    >
      <h3>{heading}</h3>
      {body}
    </section>
  );
}

/** Baseline and candidate answers side by side (stacked on a phone); `lang={case.lang}`, `pre-wrap`, text only. */
export function AnswerPair({
  locale,
  value,
  baseline,
}: {
  locale: Locale;
  value: DashboardCase;
  baseline: BaselineState;
}) {
  return (
    <div className="answer-pair">
      <BaselineSide locale={locale} baseline={baseline} />
      <Answer locale={locale} value={value} heading={t(locale, "case.candidate_answer")} />
    </div>
  );
}
