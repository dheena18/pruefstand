import type { Locale } from "@/lib/i18n";
import { t } from "@/lib/i18n";

export interface ErrorPanelProps {
  locale: Locale;
  /** The error class (`UnsupportedSchemaError`, `NotFoundError`, `ValidationError`); never a message or stack. */
  kind: string;
  onReload: () => void;
}

/** `role="alert"` panel with the error class and a reload button (ui-spec §4.8). */
export function ErrorPanel({ locale, kind, onReload }: ErrorPanelProps) {
  return (
    <section className="panel panel--error" role="alert">
      <h1>{t(locale, "error.title")}</h1>
      <p className="mono">{kind}</p>
      <div className="panel__actions">
        <button type="button" className="btn" onClick={onReload}>
          {t(locale, "error.reload")}
        </button>
      </div>
    </section>
  );
}
