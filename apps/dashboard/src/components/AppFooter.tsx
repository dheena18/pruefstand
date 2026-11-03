import { formatDate } from "@/lib/format";
import { t, type Locale } from "@/lib/i18n";
import type { FooterInfo, Licences } from "@/lib/site";

export interface AppFooterProps {
  locale: Locale;
  licences: Licences;
  info: FooterInfo;
  /** Prefix of absolute links (`/pruefstand` on GitHub Pages). Plain `<a>`: the footer also sits on the 404 page. */
  basePath: string;
}

/** Attribution line, sources link, version, export time and the "not a certificate" note on every page (§4.7). */
export function AppFooter({ locale, licences, info, basePath }: AppFooterProps) {
  return (
    <footer className="app-footer">
      <div className="app-footer__inner">
        <p lang={locale}>{licences.footer_line[locale]}</p>
        <p className="app-footer__meta">
          <a href={`${basePath}/${locale}/licences/`}>{t(locale, "footer.sources")} ›</a>
          {info.version === null ? null : <span>pruefstand v{info.version}</span>}
          {info.exportedAt === null ? null : (
            <span>
              {t(locale, "footer.exported", { date: formatDate(info.exportedAt, locale) })}
            </span>
          )}
          <span>{t(locale, "footer.no_certificate")}</span>
        </p>
      </div>
    </footer>
  );
}
