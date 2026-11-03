import { AppFooter } from "@/components/AppFooter";
import { ThemeInit } from "@/components/ThemeInit";
import { NotFoundView } from "@/components/NotFoundView";
import { BASE_PATH, footerInfo, licences } from "@/lib/site";

/** The site 404 document (`out/404.html`, de): GitHub Pages serves it for every unknown path (ui-spec §4.8). */
export default async function SiteNotFound() {
  const info = await footerInfo();
  return (
    <html lang="de" suppressHydrationWarning>
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="robots" content="noindex" />
        <title>Prüfstand</title>
        <ThemeInit />
      </head>
      <body>
        <main id="content" className="app-main">
          <NotFoundView locale="de" basePath={BASE_PATH} />
        </main>
        <AppFooter locale="de" licences={licences} info={info} basePath={BASE_PATH} />
      </body>
    </html>
  );
}
