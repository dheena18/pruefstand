import { t, type Locale } from "@/lib/i18n";

export interface NotFoundViewProps {
  locale: Locale;
  /** `basePath` of the build; the documentation link exists only when it is set (ui-spec §4.8). */
  basePath: string;
}

/**
 * The site 404 and the locale 404: one `h1` and plain `<a href>` links (this page is served for any unknown
 * path, so links are absolute and never `next/link`). The docs link is shown only when `basePath` is set,
 * because in a local build `/docs/` would itself be a 404.
 */
export function NotFoundView({ locale, basePath }: NotFoundViewProps) {
  const other = locale === "de" ? "en" : "de";
  return (
    <section className="panel">
      <h1>{t(locale, "notfound.title")}</h1>
      <div className="panel__actions">
        <a href={`${basePath}/${locale}/`}>{t(locale, "notfound.back")}</a>
        <a href={`${basePath}/${other}/`} hrefLang={other} lang={other}>
          {other === "en" ? "English" : "Deutsch"}
        </a>
        {basePath === "" ? null : <a href={`${basePath}/docs/`}>{t(locale, "notfound.docs")}</a>}
      </div>
    </section>
  );
}
