import { readFileSync } from "node:fs";
import path from "node:path";

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import CasesPage from "@/app/[locale]/runs/[id]/cases/page";
import { clearShardCache } from "@/lib/cases";
import type { DashboardCases } from "@/lib/types";

import { D_MANY, deferred, fixtureFetch, type FetchPlan } from "../cases-helpers";
import { IDS, POPULATED } from "../fixtures";

let query = "";
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/en/runs/x/cases/",
  useSearchParams: () => new URLSearchParams(query),
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

const params = (id: string, locale = "en") => ({ params: Promise.resolve({ locale, id }) });
const shard0 = (id: string) =>
  JSON.parse(readFileSync(path.join(POPULATED, "cases", id, "0.json"), "utf8")) as DashboardCases;
const original = process.env["DASHBOARD_PUBLIC_DATA"];
const serve = (plan: FetchPlan = {}) => vi.stubGlobal("fetch", fixtureFetch(plan));

beforeAll(() => {
  process.env["DASHBOARD_PUBLIC_DATA"] = POPULATED;
});
beforeEach(() => {
  query = "";
  replace.mockClear();
  clearShardCache();
  serve();
});
afterEach(() => vi.unstubAllGlobals());
afterAll(() => {
  if (original === undefined) delete process.env["DASHBOARD_PUBLIC_DATA"];
  else process.env["DASHBOARD_PUBLIC_DATA"] = original;
});

const items = (c: HTMLElement) => c.querySelectorAll(".case-item");

describe("S-HARD-FAIL (F-HARD-FAIL, tier 1)", () => {
  const failing = shard0(IDS.hardFail).cases.filter((c) => c.failing);
  it("the static default is 'Failing only' from shard 0; n failing = failing rows of shard 0; Page links only on failing rows", async () => {
    const { container } = render(await CasesPage(params(IDS.hardFail)));
    expect(failing.length).toBeGreaterThan(0);
    expect(container).toHaveTextContent(`${String(failing.length)} failing`);
    expect(container.querySelector<HTMLInputElement>("input[type='checkbox']")?.checked).toBe(true);
    expect(items(container)).toHaveLength(Math.min(25, failing.length));
    expect(container.querySelectorAll("a.case-item__page")).toHaveLength(items(container).length);
    expect(container.querySelector("main, [data-hydrated]")).toBeNull();
  });
  it("leak visible: the leak case's panel shows ⚠ LEAK for the foreign-tenant chunk", async () => {
    const leaky = failing.find((c) =>
      c.retrieved_chunk_tenant_ids.some((t) => t !== "" && t !== "shared_public" && t !== c.tenant),
    );
    expect(leaky).toBeDefined();
    query = `case=${leaky?.case_id ?? ""}`;
    const { container } = render(await CasesPage(params(IDS.hardFail)));
    await waitFor(() => expect(container.querySelector(".chunk[data-kind='leak']")).not.toBeNull());
    expect(container).toHaveTextContent("⚠ LEAK");
    expect(
      screen.getByRole("heading", { level: 2, name: `Case ${leaky?.case_id ?? ""}` }),
    ).toBeInTheDocument();
  });
  it("'all' view (failing=0): passing rows have no Page link", async () => {
    query = "failing=0";
    const { container } = render(await CasesPage(params(IDS.hardFail)));
    await waitFor(() => expect(items(container).length).toBeGreaterThan(failing.length - 1));
    const rows = [...items(container)];
    const withPage = rows.filter((r) => r.querySelector("a.case-item__page") !== null);
    expect(withPage).toHaveLength(Math.min(failing.length, rows.length));
  });
  it("filters write to the URL through router.replace (failing toggle, search)", async () => {
    render(await CasesPage(params(IDS.hardFail)));
    fireEvent.click(screen.getByLabelText("Failing only"));
    expect(replace).toHaveBeenCalledWith(expect.stringContaining("failing=0"), { scroll: false });
    fireEvent.change(screen.getByLabelText("Search id or question"), {
      target: { value: "Probezeit" },
    });
    expect(replace).toHaveBeenLastCalledWith(expect.stringContaining("q=Probezeit"), {
      scroll: false,
    });
  });
});

describe("S-PASS / S-NOT-GATED: no failing case → all rows", () => {
  it.each([IDS.tier1, IDS.notGated])("%s lists everything, no failing markers", async (id) => {
    const { container } = render(await CasesPage(params(id)));
    expect(container.querySelector<HTMLInputElement>("input[type='checkbox']")?.checked).toBe(
      false,
    );
    expect(items(container)).toHaveLength(Math.min(25, shard0(id).cases.length));
    expect(container.querySelector("a.case-item__page")).toBeNull();
    expect(container).toHaveTextContent("0 failing");
  });
  it("a refused case opens in the panel with the Refused badge (SOURCE.md id)", async () => {
    query = "case=slice-007";
    const { container } = render(await CasesPage(params(IDS.notGated)));
    await waitFor(() => expect(container.querySelector(".case-detail")).not.toBeNull());
    expect(
      within(container.querySelector(".case-detail") as HTMLElement).getAllByText("Refused").length,
    ).toBeGreaterThan(0);
  });
});

describe("states", () => {
  it("S-BASELINE-MISSING: the panel says 'Baseline not exported'", async () => {
    const first = shard0(IDS.baselineMissing).cases[0]?.case_id ?? "";
    query = `case=${first}`;
    const { container } = render(await CasesPage(params(IDS.baselineMissing)));
    await waitFor(() =>
      expect(container.querySelector("[data-state='baseline-missing']")).not.toBeNull(),
    );
    expect(container).toHaveTextContent("Baseline not exported");
  });
  it("C-NOT-FOUND: an unknown case id → inline not-found with a link back to the list", async () => {
    query = "case=unknown";
    const { container } = render(await CasesPage(params(IDS.tier1)));
    await waitFor(() =>
      expect(container.querySelector("[data-state='C-NOT-FOUND']")).not.toBeNull(),
    );
    expect(container).toHaveTextContent("Case unknown not found in this run.");
    expect(screen.getByRole("link", { name: /Back to cases/ })).toBeInTheDocument();
  });
  it("C-LOADING: parts 2 and 3 pending → 'Loading cases: 1 of 3 parts' and '(partial)'; resolves", async () => {
    const hold = deferred();
    serve({ hold: { 1: hold.promise, 2: hold.promise } });
    const { container } = render(await CasesPage(params(D_MANY)));
    await waitFor(() =>
      expect(container.querySelector("[data-state='C-LOADING']")).toHaveTextContent("1 of 3 parts"),
    );
    expect(container.querySelector(".cases-head")).toHaveTextContent("(partial)");
    hold.resolve();
    await waitFor(() => expect(container.querySelector("[data-state='C-LOADING']")).toBeNull());
    expect(container.querySelector(".cases-head")).toHaveTextContent("Cases (1500)");
    expect(container.querySelector(".cases-head")).not.toHaveTextContent("(partial)");
  });
  it("C-SHARD-ERROR: a failed part shows an alert with Retry; loaded parts stay; Retry loads it", async () => {
    serve({ fail: [1] });
    const { container } = render(await CasesPage(params(D_MANY)));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Part 2 of the cases could not be loaded.");
    await waitFor(() =>
      expect(container.querySelector(".cases-head")).toHaveTextContent("Cases (1000)"),
    );
    serve();
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(container.querySelector(".cases-head")).toHaveTextContent("Cases (1500)");
  });
  it("de: header and checkbox", async () => {
    const { container } = render(await CasesPage(params(IDS.hardFail, "de")));
    expect(container.querySelector(".cases-head")).toHaveTextContent("fehlschlagend");
    expect(screen.getByLabelText("Nur fehlschlagende")).toBeInTheDocument();
  });
});
