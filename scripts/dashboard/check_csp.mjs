// `check_csp.mjs <out dir>`: fails the build on any of the ui-spec §7.4 violations (exit 1, one line each).
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  CSP_META,
  HEAD_OPEN,
  inlineScripts,
  pagesOutsideData,
  reports,
  sha256Base64,
} from "./csp_lib.mjs";

const FORBIDDEN_FILES = ["headers.json", "_headers", "vercel.json"];

const policies = (html) => [...html.matchAll(CSP_META)].map((m) => m[1]);
const hashesOf = (policy) =>
  [...(/script-src([^;]*)/.exec(policy)?.[1] ?? "").matchAll(/'sha256-([^']+)'/g)].map((m) => m[1]);

/** Findings of one site page (Next.js output, outside data/). */
export function checkPage(html) {
  const found = [];
  const metas = policies(html);
  if (metas.length !== 1) return [`${metas.length} CSP <meta> elements, exactly one is required`];
  const policy = metas[0];
  const head = HEAD_OPEN.exec(html);
  const lead = head === null ? "" : html.slice(head.index + head[0].length, head.index + head[0].length + 70);
  if (!lead.startsWith('<meta http-equiv="Content-Security-Policy"')) found.push("the CSP <meta> is not the first child of <head>");
  if (/\sstyle\s*=/i.test(html)) found.push("a style= attribute");
  if (/<style[\s>]/i.test(html)) found.push("a <style> element");
  if (/'unsafe-inline'/.test(/script-src[^;]*/.exec(policy)?.[0] ?? "")) found.push("'unsafe-inline' in script-src");
  if (/frame-ancestors/.test(policy)) found.push("frame-ancestors in a <meta> policy (ignored by browsers)");
  const allowed = new Set(hashesOf(policy));
  for (const script of inlineScripts(html)) {
    if (!allowed.has(sha256Base64(script))) found.push(`an inline <script> without a hash (${script.slice(0, 40).replace(/\s+/g, " ")}…)`);
  }
  return found;
}

/** Findings of one exported report.html: its own policy, hash equal to its own inline script. */
export function checkReport(html) {
  const metas = policies(html);
  if (metas.length !== 1) return [`${metas.length} CSP <meta> elements, exactly one is required`];
  const scripts = inlineScripts(html);
  const allowed = hashesOf(metas[0]);
  const found = [];
  for (const script of scripts) {
    if (!allowed.includes(sha256Base64(script))) found.push("the inline script does not match the hash in the report's CSP");
  }
  if (scripts.length > 0 && allowed.length === 0) found.push("no script hash in the report's CSP");
  return found;
}

export function checkOut(root) {
  const findings = [];
  for (const name of FORBIDDEN_FILES) {
    if (existsSync(path.join(root, name))) findings.push(`${name}: Pages cannot send headers; every policy is a <meta>`);
  }
  for (const page of pagesOutsideData(root)) {
    for (const message of checkPage(readFileSync(page, "utf8"))) findings.push(`${path.relative(root, page)}: ${message}`);
  }
  for (const report of reports(root)) {
    for (const message of checkReport(readFileSync(report, "utf8"))) findings.push(`${path.relative(root, report)}: ${message}`);
  }
  return findings;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const out = path.resolve(process.argv[2] ?? "out");
  const findings = checkOut(out);
  if (findings.length > 0) {
    for (const line of findings.slice(0, 50)) console.error(line);
    process.exit(1);
  }
  console.log(`check_csp: ok (${pagesOutsideData(out).length} pages, ${reports(out).length} reports)`);
}
