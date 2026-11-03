// The CSP mechanics of ui-spec §7.4 on real builds of the two fixture sets (needs `build_set.sh`, ~1 min each).
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { APP, buildSet, node } from "./helpers";

const SETS = path.join(APP, ".sets");
const prebuilt = process.env["DASHBOARD_SETS_PREBUILT"] === "1";
const BUILD_MS = 900_000;

function pages(root: string): string[] {
  const found: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, name.name);
      if (name.isDirectory()) {
        if (!(dir === root && name.name === "data")) walk(full);
      } else if (name.name.endsWith(".html")) found.push(full);
    }
  };
  walk(root);
  return found;
}

const metas = (html: string) =>
  [...html.matchAll(/<meta http-equiv="Content-Security-Policy" content="([^"]*)"/g)].map(
    (m) => m[1] ?? "",
  );
const inline = (html: string) =>
  [...html.matchAll(/<script(?![^>]*\ssrc\s*=)[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1] ?? "");
const hash = (text: string) =>
  `'sha256-${createHash("sha256").update(text, "utf8").digest("base64")}'`;
const read = (...parts: string[]) => readFileSync(path.join(SETS, ...parts), "utf8");

beforeAll(async () => {
  if (prebuilt) return;
  for (const set of ["populated", "empty"] as const) {
    const { code, out } = await buildSet(set);
    expect(code, out).toBe(0);
  }
}, BUILD_MS);

describe("populated set", () => {
  const root = path.join(SETS, "populated");

  it("starts every page's <head> with exactly one CSP meta whose hashes match its inline scripts", () => {
    const all = pages(root);
    expect(all.length).toBeGreaterThan(5);
    for (const file of all) {
      const html = readFileSync(file, "utf8");
      const found = metas(html);
      expect(found, file).toHaveLength(1);
      const policy = found[0] ?? "";
      const head = /<head[^>]*>/.exec(html);
      expect(html.slice((head?.index ?? 0) + (head?.[0].length ?? 0))).toMatch(
        /^<meta http-equiv="Content-Security-Policy"[^>]*\/><meta name="referrer" content="strict-origin-when-cross-origin"\/>/,
      );
      const scriptSrc = /script-src([^;]*)/.exec(policy)?.[1] ?? "";
      expect(scriptSrc).not.toContain("unsafe-inline");
      for (const script of inline(html)) expect(scriptSrc, file).toContain(hash(script));
      expect(policy).not.toContain("frame-ancestors");
    }
  });

  it("has no header files and no .nojekyll, and no style attribute or <style> element", () => {
    for (const name of ["headers.json", "_headers", "vercel.json", ".nojekyll"]) {
      expect(existsSync(path.join(root, name)), name).toBe(false);
    }
    for (const file of pages(root)) {
      const html = readFileSync(file, "utf8");
      expect(html, file).not.toMatch(/\sstyle\s*=/i);
      expect(html, file).not.toMatch(/<style[\s>]/i);
    }
  });

  it("writes the redirect, the 404 and the locale roots with the right lang", () => {
    expect(read("populated", "index.html")).toContain('<html lang="de">');
    expect(read("populated", "index.html")).toContain('http-equiv="refresh" content="0; url=de/"');
    expect(read("populated", "404.html")).toContain('<html lang="de">');
    expect(read("populated", "de", "index.html")).toContain('<html lang="de">');
    expect(read("populated", "en", "index.html")).toContain('<html lang="en">');
    const serve = JSON.parse(read("populated", "serve.json")) as Record<string, unknown>;
    expect(serve).toEqual({ cleanUrls: false, trailingSlash: true });
    expect(serve).not.toHaveProperty("headers");
  });

  it("has the footer attribution on the redirect, the 404 and the locale pages", () => {
    for (const file of ["index.html", "404.html", "de/index.html", "en/index.html"]) {
      expect(read("populated", file), file).toContain("<footer");
    }
    expect(read("populated", "en", "index.html")).toContain("Questions derived from GermanQuAD");
  });

  it("copies every report.html byte for byte and each carries one CSP meta matching its script", () => {
    const runs = path.join(root, "data", "runs");
    const sources = path.join(APP, "fixtures", "populated", "runs");
    let n = 0;
    for (const id of readdirSync(runs).filter((d) =>
      existsSync(path.join(runs, d, "report.html")),
    )) {
      n += 1;
      const exported = readFileSync(path.join(runs, id, "report.html"), "utf8");
      expect(exported).toBe(readFileSync(path.join(sources, id, "report.html"), "utf8"));
      const found = metas(exported);
      expect(found).toHaveLength(1);
      for (const script of inline(exported)) expect(found[0]).toContain(hash(script));
    }
    expect(n).toBeGreaterThan(0);
  });

  it("has no demo origin in connect-src without NEXT_PUBLIC_DEMO_API_URL and no Try-it link", () => {
    for (const file of pages(root)) {
      expect(metas(readFileSync(file, "utf8"))[0], file).toContain("connect-src 'self';");
    }
    expect(read("populated", "de", "index.html")).not.toContain("/de/try/");
  });
});

describe("empty set", () => {
  it("builds out/de/runs/_empty/index.html with noindex and the empty.runs text (Y7.2)", () => {
    const html = read("empty", "de", "runs", "_empty", "index.html");
    expect(html).toContain('name="robots" content="noindex');
    expect(html).toContain("Noch keine Läufe exportiert.");
    expect(read("empty", "en", "runs", "_empty", "index.html")).toContain("No runs exported yet.");
    expect(existsSync(path.join(SETS, "empty", ".nojekyll"))).toBe(false);
  });
});

describe("check_csp", () => {
  const dirs: string[] = [];
  afterAll(() => {
    for (const d of dirs) rmSync(d, { recursive: true, force: true });
  });
  function tmpSite(page: string, extra: Record<string, string> = {}) {
    const d = mkdtempSync(path.join(tmpdir(), "dash-csp-"));
    dirs.push(d);
    writeFileSync(path.join(d, "index.html"), page);
    for (const [name, text] of Object.entries(extra)) writeFileSync(path.join(d, name), text);
    return d;
  }
  const csp = "default-src 'self'; script-src 'self'";
  const page = (body: string) =>
    `<!DOCTYPE html><html><head><meta http-equiv="Content-Security-Policy" content="${csp}"/></head><body>${body}</body></html>`;

  it("accepts a clean page and fails on style=, <style>, an unhashed inline script, or a header file", () => {
    expect(node("check_csp.mjs", [tmpSite(page("<p>ok</p>"))]).code).toBe(0);
    expect(node("check_csp.mjs", [tmpSite(page('<p style="color:red">x</p>'))]).code).toBe(1);
    expect(node("check_csp.mjs", [tmpSite(page("<style>p{}</style>"))]).code).toBe(1);
    expect(node("check_csp.mjs", [tmpSite(page("<script>alert(1)</script>"))]).code).toBe(1);
    expect(node("check_csp.mjs", [tmpSite(page("<p>ok</p>"), { _headers: "/*" })]).code).toBe(1);
    expect(node("check_csp.mjs", [tmpSite("<html><head></head><body></body></html>")]).code).toBe(
      1,
    );
  });

  it("checks each report against its own script hash, whatever _sort.js version rendered it (UI11-10)", () => {
    for (const script of ["window.a=1;", "window.sortTables=function(){return 2};"]) {
      const d = mkdtempSync(path.join(tmpdir(), "dash-csp-"));
      dirs.push(d);
      writeFileSync(path.join(d, "index.html"), page("<p>ok</p>"));
      const dir = path.join(d, "data", "runs", "r1");
      mkdirSync(dir, { recursive: true });
      const report = (h: string) =>
        `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src ${h}; img-src data:; base-uri 'none'; form-action 'none'"></head><body><script>${script}</script></body></html>`;
      writeFileSync(path.join(dir, "report.html"), report(hash(script)));
      expect(node("check_csp.mjs", [d]).code).toBe(0);
      writeFileSync(path.join(dir, "report.html"), report("'sha256-AAAA'"));
      expect(node("check_csp.mjs", [d]).code).toBe(1);
    }
  });

  it("csp.mjs is idempotent and adds the demo origin to connect-src only when asked", () => {
    const d = tmpSite(
      "<!DOCTYPE html><html><head><title>t</title></head><body><script>1</script></body></html>",
    );
    expect(
      node("csp.mjs", [d], { NEXT_PUBLIC_DEMO_API_URL: "https://demo.example.test/api" }).code,
    ).toBe(0);
    const once = readFileSync(path.join(d, "index.html"), "utf8");
    expect(once).toContain("connect-src 'self' https://demo.example.test;");
    expect(
      node("csp.mjs", [d], { NEXT_PUBLIC_DEMO_API_URL: "https://demo.example.test/api" }).code,
    ).toBe(0);
    expect(readFileSync(path.join(d, "index.html"), "utf8")).toBe(once);
    expect(node("check_csp.mjs", [d]).code).toBe(0);
  });
});

describe("build env", () => {
  it(
    "a build with NEXT_BASE_PATH=/x prefixes theme-init.js and internal links, and sets the demo origin",
    async () => {
      const { code, out } = await buildSet("populated", "populated-x", {
        NEXT_BASE_PATH: "/x",
        NEXT_PUBLIC_DEMO_API_URL: "https://demo.example.test",
      });
      expect(code, out).toBe(0);
      const html = read("populated-x", "de", "index.html");
      expect(html).toContain('src="/x/theme-init.js"');
      expect(html).toContain('href="/x/de/licences/"');
      expect(html).toContain("/x/de/try/");
      expect(html).not.toMatch(/href="\/(de|en)\//);
      expect(metas(html)[0]).toContain("connect-src 'self' https://demo.example.test;");
      expect(read("populated-x", "404.html")).toContain('href="/x/docs/"');
    },
    BUILD_MS,
  );
});
