// Shared by csp.mjs and check_csp.mjs: finding pages and inline scripts (ui-spec §7.4). No dependency.
import { createHash } from "node:crypto";
import { readdirSync, statSync } from "node:fs";
import path from "node:path";

/** Every `*.html` below `root`, skipping the exported data tree `data/` at the root. */
export function pagesOutsideData(root) {
  const found = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) {
        if (!(dir === root && name === "data")) walk(full);
      } else if (name.endsWith(".html")) found.push(full);
    }
  };
  walk(root);
  return found.sort();
}

/** `out/data/runs/<id>/report.html` files. */
export function reports(root) {
  const runs = path.join(root, "data", "runs");
  let ids = [];
  try {
    ids = readdirSync(runs).filter((n) => statSync(path.join(runs, n)).isDirectory());
  } catch {
    return [];
  }
  return ids
    .map((id) => path.join(runs, id, "report.html"))
    .filter((p) => {
      try {
        return statSync(p).isFile();
      } catch {
        return false;
      }
    })
    .sort();
}

const INLINE_SCRIPT = /<script(?![^>]*\ssrc\s*=)([^>]*)>([\s\S]*?)<\/script>/gi;

/** The text of every inline `<script>` (no `src`) of a page, in order. */
export function inlineScripts(html) {
  return [...html.matchAll(INLINE_SCRIPT)].map((m) => m[2]);
}

export const sha256Base64 = (text) => createHash("sha256").update(text, "utf8").digest("base64");

export const CSP_META = /<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]*)"\s*\/?>/gi;
export const REFERRER_META = /<meta\s+name="referrer"\s+content="[^"]*"\s*\/?>/gi;
export const HEAD_OPEN = /<head(\s[^>]*)?>/i;
