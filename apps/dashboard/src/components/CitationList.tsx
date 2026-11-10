import { t, type Locale } from "@/lib/i18n";

/** Citations as text chips; German legal references, so `lang="de"` (ui-spec §4.5.4). */
export function CitationList({
  locale,
  citations,
}: {
  locale: Locale;
  citations: readonly string[];
}) {
  if (citations.length === 0) return <p className="muted">{t(locale, "case.no_citations")}</p>;
  return (
    <ul className="chips">
      {citations.map((c, i) => (
        <li key={`${c}-${String(i)}`} lang="de" className="chip">
          {c}
        </li>
      ))}
    </ul>
  );
}
