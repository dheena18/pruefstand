import { AppFooter } from "@/components/AppFooter";
import { ThemeInit } from "@/components/ThemeInit";
import { t } from "@/lib/i18n";
import { BASE_PATH, footerInfo, licences } from "@/lib/site";

/**
 * Root redirect document, exported as `out/index.html` (ui-spec §2.1): `meta refresh` to `de/`, a visible link,
 * `noindex`, the footer. No script of ours except the blocking theme file, no stored-locale lookup.
 */
export default async function RootRedirect() {
  const info = await footerInfo();
  return (
    <html lang="de" suppressHydrationWarning>
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta httpEquiv="refresh" content="0; url=de/" />
        <meta name="robots" content="noindex" />
        <title>Prüfstand</title>
        <ThemeInit />
      </head>
      <body>
        <main id="content" className="app-main">
          <section className="panel">
            <h1>Prüfstand</h1>
            <p>
              <a href="de/">{t("de", "redirect.continue")}</a>
            </p>
          </section>
        </main>
        <AppFooter locale="de" licences={licences} info={info} basePath={BASE_PATH} />
      </body>
    </html>
  );
}
