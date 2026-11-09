import { fireEvent, render, screen, within } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { RunsListView, flagsOf, workloadCell } from "@/components/RunsListView";
import type { RunIndexEntry } from "@/lib/types";

import { EMPTY, POPULATED, indexOf } from "../fixtures";

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/de/",
  useSearchParams: () => new URLSearchParams(search),
}));

let runs: RunIndexEntry[];
beforeAll(async () => {
  runs = await indexOf();
});
beforeEach(() => {
  replace.mockClear();
  search = "";
});

const view = (locale: "de" | "en", query = "") => (
  <RunsListView locale={locale} runs={runs} query={query} />
);

describe("runs list: L-POPULATED (D-MANY)", () => {
  it("the fixture set has ≥ 60 runs", () => {
    expect(runs.length).toBeGreaterThanOrEqual(60);
  });
  it("static render without a query is the default view: page 1, created desc, no skeleton (UI11-09)", () => {
    const html = renderToStaticMarkup(view("en"));
    expect(html).not.toContain("skeleton");
    const newest = [...runs].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
    expect(newest).toBeDefined();
    expect(html).toContain(`/en/runs/${newest?.run_id ?? ""}/`);
    expect(html).toContain("Showing 1–25 of 62 runs · sorted by Created ↓");
    expect(html).toContain('aria-sort="descending"');
  });
  it("≥ 3 pages with Pagination links", () => {
    render(view("en"));
    const nav = screen.getByRole("navigation", { name: "Pages" });
    expect(within(nav).getByRole("link", { name: "3" })).toHaveAttribute("href", "/de/?page=3");
    render(view("en", "page=3"));
    expect(screen.getAllByText(/Showing 51–62 of 62 runs/).length).toBe(1);
  });
  it("shows the table columns of ui-spec §4.1 in de", () => {
    render(view("de"));
    const heads = screen
      .getAllByRole("columnheader")
      .map((h) => h.textContent?.replace(/\s*\(.*\)|\s*[↑↓]/g, "").trim());
    expect(heads).toEqual([
      "Status",
      "Ref",
      "PR",
      "Erstellt",
      "Stufe",
      "Workload",
      "Fälle",
      "Dauer",
      "Kosten",
      "Hinweise",
    ]);
  });
  it("the Tier header has the visually hidden explanation", () => {
    render(view("en"));
    expect(screen.getAllByText(/Tier 1: hosted CPU smoke run/)[0]).toHaveClass("sr-only");
  });
  it("filters by status incl. no_baseline and not_gated, and by tier", () => {
    const { container } = render(view("en", "status=no_baseline"));
    expect(container.querySelectorAll("tbody [data-status='NO_BASELINE']").length).toBe(1);
    expect(container.querySelector("tbody [data-status='pass']")).toBeNull();
    expect(screen.getAllByText(/Showing 1–1 of 1 runs/)).toHaveLength(1);
    render(view("en", "status=not_gated&tier=1"));
    expect(screen.getAllByText("NOT GATED").length).toBeGreaterThan(0);
  });
  it("NOT GATED is never PASS; the F-NO-BASELINE row shows NO BASELINE", () => {
    const html = renderToStaticMarkup(
      <RunsListView locale="en" query="status=not_gated" runs={runs} />,
    );
    expect(html).toContain("NOT GATED");
    expect(html).not.toContain('data-status="pass"');
  });
  it("sort button toggles direction and a filter change resets the page via the URL", () => {
    render(view("en", "page=2"));
    fireEvent.click(screen.getAllByRole("button", { name: /Duration/ })[0] as HTMLElement);
    expect(replace).toHaveBeenLastCalledWith("/de/?sort=duration", { scroll: false });
    fireEvent.change(screen.getByLabelText("Tier"), { target: { value: "2" } });
    expect(replace).toHaveBeenLastCalledWith("/de/?tier=2", { scroll: false });
  });
  it("the count sits in an aria-live region", () => {
    const { container } = render(view("en", "workload=nightly"));
    expect(container.querySelector("[aria-live='polite']")?.textContent).toMatch(/results?$/);
  });
});

describe("workload cell and flags (UI13-19)", () => {
  const clone = (over: Partial<RunIndexEntry>) => ({ ...(runs[0] as RunIndexEntry), ...over });
  it("nightly · b1, pr · subset, plain pr; de uses Teilmenge", () => {
    expect(workloadCell(clone({ workload: "nightly", block: 1, judged_subset: false }), "en")).toBe(
      "nightly · b1",
    );
    expect(workloadCell(clone({ workload: "pr", block: null, judged_subset: true }), "en")).toBe(
      "pr · subset",
    );
    expect(workloadCell(clone({ workload: "pr", block: null, judged_subset: true }), "de")).toBe(
      "pr · Teilmenge",
    );
    expect(workloadCell(clone({ workload: "pr", block: null, judged_subset: false }), "en")).toBe(
      "pr",
    );
  });
  it("flags are text", () => {
    const flags = flagsOf(
      clone({
        complete: false,
        judge_mode: "skipped",
        judge_fallback: true,
        judge_degraded: true,
        judge_drift: true,
      }),
      "en",
    );
    expect(flags).toEqual([
      "incomplete",
      "judge skipped",
      "judge fallback",
      "judge degraded",
      "judge drift",
    ]);
    expect(
      flagsOf(
        clone({
          complete: true,
          judge_mode: "github",
          judge_fallback: false,
          judge_degraded: false,
          judge_drift: false,
        }),
        "en",
      ),
    ).toEqual([]);
  });
  it("renders a nightly clone's cell in the table", () => {
    const rows = [{ ...(runs[0] as RunIndexEntry), workload: "nightly" as const, block: 1 }];
    render(<RunsListView locale="de" runs={rows} query="" />);
    expect(screen.getAllByText("nightly · b1").length).toBeGreaterThan(0);
  });
});

describe("L-FILTERED-EMPTY and L-EMPTY", () => {
  it("L-FILTERED-EMPTY offers Clear filters", () => {
    render(view("en", "status=unsupported_config&tier=1"));
    expect(screen.getByText("No runs match these filters.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(replace).toHaveBeenLastCalledWith("/de/", { scroll: false });
  });
  it("L-EMPTY: the page for fixtures/empty shows empty.runs", async () => {
    process.env["DASHBOARD_PUBLIC_DATA"] = EMPTY;
    const { default: RunsPage } = await import("@/app/[locale]/page");
    const { container } = render(await RunsPage({ params: Promise.resolve({ locale: "en" }) }));
    expect(container).toHaveTextContent("No runs exported yet.");
    expect(container.querySelector("[data-state='L-EMPTY']")).not.toBeNull();
    process.env["DASHBOARD_PUBLIC_DATA"] = POPULATED;
  });
  it("the populated page renders the list inside Suspense and sets data-hydrated", async () => {
    process.env["DASHBOARD_PUBLIC_DATA"] = POPULATED;
    const { default: RunsPage } = await import("@/app/[locale]/page");
    render(<main>{await RunsPage({ params: Promise.resolve({ locale: "de" }) })}</main>);
    expect(await screen.findByRole("heading", { level: 1, name: "Läufe" })).toBeInTheDocument();
    expect(document.querySelector("main")).toHaveAttribute("data-hydrated", "true");
  });
});
