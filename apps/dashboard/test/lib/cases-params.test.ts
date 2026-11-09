import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { generateStaticParams } from "@/app/[locale]/runs/[id]/cases/page";

import { IDS, POPULATED, indexOf } from "../fixtures";
import { dataWithIndex } from "../pages-helpers";

const original = process.env["DASHBOARD_PUBLIC_DATA"];
beforeAll(() => {
  process.env["DASHBOARD_PUBLIC_DATA"] = POPULATED;
});
afterAll(() => {
  if (original === undefined) delete process.env["DASHBOARD_PUBLIC_DATA"];
  else process.env["DASHBOARD_PUBLIC_DATA"] = original;
});

describe("cases list generateStaticParams", () => {
  it("returns exactly the runs with cases/<id>/0.json (the newest 20), never a pruned run", async () => {
    const published = readdirSync(path.join(POPULATED, "cases")).sort();
    const got = (await generateStaticParams())
      .filter((p) => p.locale === "de")
      .map((p) => p.id)
      .sort();
    expect(got).toEqual(published);
    expect(got).toHaveLength(20);
    expect(got).not.toContain(IDS.pruned);
    for (const id of got)
      expect(statSync(path.join(POPULATED, "cases", id, "0.json")).isFile()).toBe(true);
  });
  it("an empty set → [{id: '_empty'}] per locale (UI12-08)", async () => {
    const dir = await dataWithIndex((await indexOf()).filter((r) => r.run_id === IDS.pruned));
    process.env["DASHBOARD_PUBLIC_DATA"] = dir;
    try {
      expect(await generateStaticParams()).toEqual([
        { locale: "de", id: "_empty" },
        { locale: "en", id: "_empty" },
      ]);
    } finally {
      process.env["DASHBOARD_PUBLIC_DATA"] = POPULATED;
    }
  });
});

describe("runtime URLs (UI12-05)", () => {
  function sources(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) return name === "generated" ? [] : sources(full);
      return /\.(ts|tsx)$/.test(name) ? [full] : [];
    });
  }
  it("src/ has no string literal starting with /data/ or /_next/", () => {
    const bad = sources(path.join(__dirname, "../../src")).filter((f) =>
      /["'`]\/(data|_next)\//.test(readFileSync(f, "utf8")),
    );
    expect(bad).toEqual([]);
  });
});
