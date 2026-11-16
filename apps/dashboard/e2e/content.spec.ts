// Content rules (ui-spec §7, §9): no canary token anywhere in a built site, and every page carries the attribution.
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    return statSync(full).isDirectory() ? files(full) : [full];
  });
}

test("no built file of the fixture site contains a canary token", ({}, testInfo) => {
  const set = String(testInfo.project.metadata["set"]);
  const root = path.join(import.meta.dirname, "..", ".sets", set);
  const hits = files(root)
    .filter((f) => /\.(html|json|txt|js)$/.test(f))
    .filter((f) => /CANARY-/.test(readFileSync(f, "utf8")));
  expect(hits.map((f) => path.relative(root, f))).toEqual([]);
});

test("the root redirect document and the 404 page carry the attribution footer", async ({
  request,
}) => {
  const root = await (await request.get("/")).text();
  expect(root).toContain('class="app-footer"');
  const missing = await request.get("/does-not-exist/");
  expect(missing.status()).toBe(404);
  expect(await missing.text()).toContain('class="app-footer"');
});
