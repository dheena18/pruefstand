import type { Ref } from "react";

import { t, type Locale } from "@/lib/i18n";
import type { Answer } from "@/lib/try-state";

import { CitationList } from "./CitationList";
import { TenantBadge } from "./TenantBadge";

export interface AnswerCardProps {
  locale: Locale;
  answer: Answer;
  elapsedS: number;
  tenant: string;
  /** Receives the focus when the answer arrives (ui-spec §4.6). */
  headingRef?: Ref<HTMLHeadingElement>;
}

/** The answer, its citations and the retrieved chunks of one Try-it query. Text only, never HTML. */
export function AnswerCard({ locale, answer, elapsedS, tenant, headingRef }: AnswerCardProps) {
  return (
    <section className="try-answer" aria-labelledby="try-answer-h">
      <h2 id="try-answer-h" tabIndex={-1} ref={headingRef}>
        {t(locale, "try.answer")}
      </h2>
      <p className="try-answer__meta">
        {t(locale, "try.elapsed", { s: elapsedS })}
        {answer.model === null ? "" : ` · ${answer.model}`}
      </p>
      {answer.refused ? (
        <p className="badge badge--neutral" data-state="refused">
          {t(locale, "try.refused")}
        </p>
      ) : null}
      <p lang="de" className="case-text pre-wrap">
        {answer.answer}
      </p>
      <CitationList locale={locale} citations={answer.citations} />
      <h3>{t(locale, "try.chunks")}</h3>
      <ol className="try-chunks">
        {answer.chunks.map((c) => (
          <li key={c.chunk_id} className="try-chunk" data-chunk={c.chunk_id}>
            <p lang="de" className="try-chunk__text">
              {c.text}
            </p>
            <p className="try-chunk__meta">
              <span className="mono" lang="de">
                {c.doc_id}
              </span>
              {` · ${c.score.toFixed(2)} `}
              {c.tenant_id === null ? null : (
                <TenantBadge locale={locale} tenant={c.tenant_id} caseTenant={tenant} />
              )}
              {c.used_in_prompt === false ? (
                <span className="try-chunk__note">{` · ${t(locale, "try.not_in_prompt")}`}</span>
              ) : null}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
