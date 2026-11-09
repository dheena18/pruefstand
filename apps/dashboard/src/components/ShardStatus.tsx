import { t, type Locale } from "@/lib/i18n";

export interface ShardStatusProps {
  locale: Locale;
  nShards: number;
  loaded: number;
  failed: readonly number[];
  onRetry: (shard: number) => void;
}

/**
 * `C-LOADING`: "Loading cases: 2 of 3 parts" (`aria-live="polite"`) while a part is pending;
 * `C-SHARD-ERROR`: an inline alert with Retry for each failed part. Loaded parts stay usable (ui-spec §4.5.1).
 */
export function ShardStatus({ locale, nShards, loaded, failed, onRetry }: ShardStatusProps) {
  const pending = loaded + failed.length < nShards;
  return (
    <>
      {pending ? (
        <p className="shard-status" data-state="C-LOADING" aria-live="polite">
          {t(locale, "cases.loading", { loaded, total: nShards })}
        </p>
      ) : null}
      {failed.map((shard) => (
        <section
          key={shard}
          className="panel panel--error panel--inline"
          role="alert"
          data-state="C-SHARD-ERROR"
        >
          <p>{t(locale, "shard.error", { n: shard + 1 })}</p>
          <button type="button" className="btn" onClick={() => onRetry(shard)}>
            {t(locale, "shard.retry")}
          </button>
        </section>
      ))}
    </>
  );
}
