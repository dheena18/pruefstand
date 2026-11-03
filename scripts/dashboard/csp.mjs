// `csp.mjs <out dir>`: post-build CSP for the static export (ui-spec §7.4). GitHub Pages sends no headers, so
// every policy is a <meta> with the sha256 of each inline script Next.js emitted into that page. It inserts the
// CSP meta and the referrer meta as the first children of <head>, adds the Try-it origin to `connect-src` only
// when NEXT_PUBLIC_DEMO_API_URL is set, and never touches out/data/** (a report.html carries its own policy).
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  CSP_META,
  HEAD_OPEN,
  REFERRER_META,
  inlineScripts,
  pagesOutsideData,
  sha256Base64,
} from "./csp_lib.mjs";

/** The policy string for a page with these inline scripts. */
export function policy(scripts, demoApiUrl = "") {
  const hashes = [...new Set(scripts.map((s) => `'sha256-${sha256Base64(s)}'`))];
  const origin = demoApiUrl === "" ? "" : ` ${new URL(demoApiUrl).origin}`;
  return [
    "default-src 'self'",
    ["script-src 'self'", ...hashes].join(" "),
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    `connect-src 'self'${origin}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
}

/** Insert (or replace) the metas in one page; idempotent. */
export function addMetas(html, demoApiUrl = "") {
  const clean = html.replace(CSP_META, "").replace(REFERRER_META, "");
  const head = HEAD_OPEN.exec(clean);
  if (head === null) throw new Error("page has no <head>");
  const metas =
    `<meta http-equiv="Content-Security-Policy" content="${policy(inlineScripts(clean), demoApiUrl)}"/>` +
    `<meta name="referrer" content="strict-origin-when-cross-origin"/>`;
  const at = head.index + head[0].length;
  return clean.slice(0, at) + metas + clean.slice(at);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const out = path.resolve(process.argv[2] ?? "out");
  const demo = process.env["NEXT_PUBLIC_DEMO_API_URL"] ?? "";
  const pages = pagesOutsideData(out);
  for (const page of pages) writeFileSync(page, addMetas(readFileSync(page, "utf8"), demo));
  console.log(`csp: ${pages.length} pages`);
}
