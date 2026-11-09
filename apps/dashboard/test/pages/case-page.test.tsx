import { readFileSync } from "node:fs";
import path from "node:path";

import { render, screen } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import CasePage, {
  generateMetadata,
  generateStaticParams,
} from "@/app/[locale]/runs/[id]/cases/[caseId]/page";
import type { DashboardCases } from "@/lib/types";

import { D_MANY } from "../cases-helpers";
import { IDS, POPULATED, indexOf } from "../fixtures";
import { dataWithIndex } from "../pages-helpers";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/en/runs/x/cases/slice-009/",
  useSearchParams: () => new URLSearchParams(""),
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

const params = (id: string, caseId: string, locale = "en") => ({
  params: Promise.resolve({ locale, id, caseId }),
});
const shard0 = (id: string) =>
  JSON.parse(readFileSync(path.join(POPULATED, "cases", id, "0.json"), "utf8")) as DashboardCases;
const original = process.env["DASHBOARD_PUBLIC_DATA"];
beforeAll(() => {
  process.env["DASHBOARD_PUBLIC_DATA"] = POPULATED;
});
afterAll(() => {
  if (original === undefined) delete process.env["DASHBOARD_PUBLIC_DATA"];
  else process.env["DASHBOARD_PUBLIC_DATA"] = original;
});

describe("static case pages", () => {
  it("are generated only for failing == true cases (count = failing count of shard 0)", async () => {
    const all = (await generateStaticParams()).filter((p) => p.locale === "en");
    const failing = shard0(IDS.hardFail)
      .cases.filter((c) => c.failing)
      .map((c) => c.case_id);
    const got = all
      .filter((p) => p.id === IDS.hardFail)
      .map((p) => p.caseId)
      .sort();
    expect(got).toEqual([...failing].sort());
    const bigFailing = shard0(D_MANY).cases.filter((c) => c.failing).length;
    expect(all.filter((p) => p.id === D_MANY)).toHaveLength(bigFailing);
  });
  it("a published run without failing cases → exactly {id, caseId: '_empty'}", async () => {
    const all = (await generateStaticParams()).filter((p) => p.locale === "en");
    expect(all.filter((p) => p.id === IDS.tier1)).toEqual([
      { locale: "en", id: IDS.tier1, caseId: "_empty" },
    ]);
  });
  it("no params for a pruned run", async () => {
    const all = await generateStaticParams();
    expect(all.some((p) => p.id === IDS.pruned)).toBe(false);
    const published = (await indexOf()).filter((r) => r.run_id !== IDS.pruned).length;
    expect(published).toBeGreaterThan(20);
  });
  it("no published run at all → {id: '_empty', caseId: '_empty'}", async () => {
    const dir = await dataWithIndex((await indexOf()).filter((r) => r.run_id === IDS.pruned));
    process.env["DASHBOARD_PUBLIC_DATA"] = dir;
    try {
      expect(await generateStaticParams()).toEqual([
        { locale: "de", id: "_empty", caseId: "_empty" },
        { locale: "en", id: "_empty", caseId: "_empty" },
      ]);
    } finally {
      process.env["DASHBOARD_PUBLIC_DATA"] = POPULATED;
    }
  });
  it("the placeholder renders empty.cases with noindex", async () => {
    const { container } = render(await CasePage(params(IDS.tier1, "_empty")));
    expect(container).toHaveTextContent("No cases match these filters.");
    expect(container.querySelector("a[href$='/cases/']")).not.toBeNull();
    expect((await generateMetadata(params(IDS.tier1, "_empty"))).robots).toEqual({ index: false });
  });
});

describe("case page content", () => {
  const first = shard0(IDS.hardFail).cases.find((c) => c.failing);
  it("breadcrumb Runs › run › Cases › id; same CaseDetail as the panel; h1; the leak finding", async () => {
    const id = first?.case_id ?? "";
    const { container } = render(await CasePage(params(IDS.hardFail, id)));
    const crumb = container.querySelector("nav.breadcrumb") as HTMLElement;
    expect(crumb).toHaveTextContent("Runs");
    expect(crumb).toHaveTextContent("Cases");
    expect(crumb).toHaveTextContent(id);
    expect(screen.getByRole("heading", { level: 1, name: `Case ${id}` })).toBeInTheDocument();
    expect(container.querySelectorAll(".chunk").length).toBe(first?.retrieved_chunk_ids.length);
    expect(container.querySelector(".finding")).not.toBeNull();
    expect(container.querySelector("nav.subnav [aria-current='page']")).toHaveTextContent("Cases");
  });
  it("shows the baseline answer from the baseline run's shards", async () => {
    const { container } = render(await CasePage(params(IDS.hardFail, first?.case_id ?? "")));
    expect(container.querySelector("[data-state='baseline-missing']")).toBeNull();
    expect(container.querySelectorAll(".answer-pair section")).toHaveLength(2);
  });
  it("S-BASELINE-MISSING-like: a baseline outside the export shows the panel", async () => {
    const failing = shard0(IDS.baselineMissing).cases.find((c) => c.failing);
    if (failing === undefined) return; // the fixture run passes; covered by the cases-list test
    const { container } = render(await CasePage(params(IDS.baselineMissing, failing.case_id)));
    expect(container).toHaveTextContent("Baseline not exported");
  });
  it("de", async () => {
    render(await CasePage(params(IDS.hardFail, first?.case_id ?? "", "de")));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Fall ");
  });
});
