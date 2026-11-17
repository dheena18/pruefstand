import { t, type Locale } from "@/lib/i18n";

export interface RetryCountdownProps {
  locale: Locale;
  /** i18n key of the message; its `{s}` is the remaining seconds. */
  messageKey: string;
  /** Seconds the server asked to wait (fixed). */
  initialS: number;
  /** Seconds left. */
  remainingS: number;
}

/**
 * The retry hint of `rate_limited` / `busy` (ui-spec §4.6): the visible text counts down, but the
 * screen-reader text is fixed so the countdown announces its start and its end only.
 */
export function RetryCountdown({ locale, messageKey, initialS, remainingS }: RetryCountdownProps) {
  return (
    <div className="panel panel--error panel--inline" role="alert" data-countdown={remainingS}>
      <p aria-hidden="true">{t(locale, messageKey, { s: remainingS })}</p>
      <p className="sr-only">
        {remainingS > 0 ? t(locale, messageKey, { s: initialS }) : t(locale, "try.retry")}
      </p>
    </div>
  );
}
