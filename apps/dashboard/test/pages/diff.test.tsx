import { readFileSync } from "node:fs";
import path from "node:path";

import { render, screen, within } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import DiffPage, {
  generateMetadata,
  generateStaticParams,
} from "@/app/[locale]/runs/[id]/diff/page";
import { DiffView } from "@/components/DiffView";
import { buildDiffModel } from "@/lib/diff";

import { IDS, POPULATED, ctxOf, decision, gateWith, indexOf, labelsOf, RESULT } from "../fixtures";
import { dataWithIndex } from "../pages-helpers";

const query = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/en/runs/x/diff/",
  useSearchParams: () => new URLSearchParams(query),
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

const params = (id: string, locale = "en") => ({ params: Promise.resolve({ locale, id }) });
const original = process.env["DASHBOARD_PUBLIC_DATA"];
beforeAll(() => {
  process.env["DASHBOARD_PUBLIC_DATA"] = POPULATED;
});
afterAll(() => {
  if (original === undefined) delete process.env["DASHBOARD_PUBLIC_DATA"];
  else process.env["DASHBOARD_PUBLIC_DATA"] = original;
});

const res = (over: Record<string, number>) => ({ ...RESULT, ...over });
const tier2 = (decisions: ReturnType<typeof decision>[]) => async () => {
  const ctx = await ctxOf(IDS.tier1);
  const gate = gateWith({ decisions });
  return buildDiffModel({ ...ctx, run: { ...ctx.run, stack: "a40" }, gate });
};

async function renderView(
  model: Awaited<ReturnType<ReturnType<typeof tier2>>>,
  q = "",
  locale: "en" | "de" = "en",
) {
  const labels = await labelsOf();
  return render(<DiffView locale={locale} labels={labels} model={model} query={q} />);
}

describe("Diff page, tier 2 states (synthetic gate reports; real T8.3 fixtures below)", () => {
  const rows = [
    decision({
      metric: "faithfulness",
      status: "pass",
      result: res({ mean_diff: -0.01, ci_low: -0.03, ci_high: 0.01 }),
    }),
    decision({
      metric: "context_recall",
      status: "fail",
      result: res({ mean_diff: -0.09, ci_low: -0.12, ci_high: -0.06 }),
    }),
    decision({
      metric: "context_recall",
      dimension: "tenant",
      value: "kanzlei_mueller",
      status: "warn",
      result: res({ mean_diff: -0.07 }),
    }),
    decision({
      metric: "citation_f1",
      dimension: "tenant",
      value: "stadtwerke_sued",
      status: "insufficient_data",
      result: null,
      n_clusters: 22,
    }),
  ];
  it("S-FAIL: a dot-and-whisker row per gated pair, default order status then Δ, summary counts", async () => {
    const { container } = await renderView(await tier2(rows)());
    expect(await screen.findAllByRole("img")).toHaveLength(4);
    expect(container.querySelector("h1")).toHaveTextContent(
      "Gated pairs (3 testable · 1 insufficient data)",
    );
    const first = within(screen.getByRole("table")).getAllByRole("row")[1] as HTMLElement;
    expect(first).toHaveTextContent("Context recall");
    expect(first).toHaveAttribute("data-status", "fail");
    expect(container).toHaveTextContent("22 clusters");
  });
  it("sort and slice filter come from the query", async () => {
    const model = await tier2(rows)();
    const a = await renderView(model, "sort=metric");
    const names = within(screen.getByRole("table"))
      .getAllByRole("row")
      .slice(1)
      .map((r) => r.querySelector("th")?.textContent);
    expect(names[0]).toContain("Citation F1");
    a.unmount();
    await renderView(model, "slice=tenant");
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(3);
  });
  it("?slice=junk falls back to all rows", async () => {
    await renderView(await tier2(rows)(), "slice=junk");
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(1 + rows.length);
  });
  it("the chart caption names the confidence of the data", async () => {
    const { container } = await renderView(await tier2(rows)());
    expect(container.querySelector("figcaption")).toHaveTextContent("Δ with 95 % CI");
  });
  it("static render without a query is the default sort (UI11-09)", async () => {
    const model = await tier2(rows)();
    const a = await renderView(model, "");
    const html = a.container.innerHTML;
    a.unmount();
    const b = await renderView(model, "sort=status&page=1");
    expect(b.container.innerHTML).toBe(html);
  });
  it("S-PASS: no failing row and no leftover status words besides PASS", async () => {
    const { container } = await renderView(await tier2([rows[0] as (typeof rows)[number]])());
    await screen.findAllByRole("img");
    expect(container).toHaveTextContent("PASS");
    expect(container).not.toHaveTextContent(/FAIL|WARN/);
  });
  it("no gated pair: an empty line, no chart", async () => {
    const { container } = await renderView(await tier2([])());
    expect(container).toHaveTextContent("No gated pairs in this run.");
    expect(container.querySelector("figure")).toBeNull();
  });
  const t2 = readIndexSync().find((r) => r.stack === "a40" && r.status !== null);
  it.skipIf(t2 === undefined)("S-FAIL/S-WARN/S-PASS on the T8.3 tier-2 fixtures", async () => {
    render(await DiffPage(params((t2 as { run_id: string }).run_id)));
    expect((await screen.findAllByRole("img")).length).toBeGreaterThan(0);
  });
});

function readIndexSync() {
  const idx = JSON.parse(readFileSync(path.join(POPULATED, "runs", "index.json"), "utf8")) as {
    runs: { run_id: string; stack: string; status: string | null }[];
  };
  return idx.runs;
}

describe("Diff page, tier 1", () => {
  it.each([IDS.tier1, IDS.hardFail])(
    "S-TIER1 / S-HARD-FAIL (%s): notice and block R, no chart",
    async (id) => {
      const { container } = render(await DiffPage(params(id)));
      expect(screen.getByRole("note")).toBeInTheDocument();
      expect(container.querySelector("figure, svg[role='img']")).toBeNull();
      expect(container).toHaveTextContent("Reported — does not decide");
      expect(container).not.toHaveTextContent("Error rate"); // block C is not on the diff page
      expect(container).not.toHaveTextContent(/FAIL|WARN/);
      expect(container.querySelector("nav.subnav [aria-current='page']")).toHaveTextContent("Diff");
    },
  );
  it("de", async () => {
    render(await DiffPage(params(IDS.tier1, "de")));
    expect(screen.getByRole("note")).toHaveTextContent("Stufe 1 entscheidet nur");
  });
});

describe("static params", () => {
  it("generates only runs with gate.json and no_baseline == false", async () => {
    const runs = await indexOf();
    const expected = runs
      .filter((r) => r.status !== null && r.no_baseline !== true)
      .map((r) => r.run_id)
      .sort();
    const got = (await generateStaticParams())
      .filter((p) => p.locale === "de")
      .map((p) => p.id)
      .sort();
    expect(got).toEqual(expected);
    expect(got).not.toContain(IDS.noBaseline);
    expect(got).not.toContain(IDS.notGated);
    expect(got).not.toContain(IDS.partial);
    expect((await generateStaticParams()).map((p) => p.locale)).toEqual(
      expect.arrayContaining(["de", "en"]),
    );
  });
  it("only no-baseline and ungated runs → [{id: '_empty'}] per locale; renders empty.runs with noindex", async () => {
    const runs = await indexOf();
    const dir = await dataWithIndex(
      runs.filter((r) => r.run_id === IDS.noBaseline || r.run_id === IDS.notGated),
    );
    process.env["DASHBOARD_PUBLIC_DATA"] = dir;
    try {
      expect(await generateStaticParams()).toEqual([
        { locale: "de", id: "_empty" },
        { locale: "en", id: "_empty" },
      ]);
      const { container } = render(await DiffPage(params("_empty", "de")));
      expect(container).toHaveTextContent("Noch keine Läufe exportiert.");
      expect((await generateMetadata(params("_empty"))).robots).toEqual({ index: false });
    } finally {
      process.env["DASHBOARD_PUBLIC_DATA"] = POPULATED;
    }
  });
});

describe("module boundaries", () => {
  const src = path.join(__dirname, "../../src");
  const read = (rel: string) => readFileSync(path.join(src, rel), "utf8");
  const targets = (code: string) =>
    [...code.matchAll(/(?:from |import\()"([^"]+)"/g)].map((m) => m[1] as string);
  it("the page imports no chart module; the chart wrapper is the only importer of the plot (UI11-22)", () => {
    const page = targets(read("app/[locale]/runs/[id]/diff/page.tsx"));
    expect(page.some((p) => /(CiChart|CiBar|CiPlot)/.test(p))).toBe(false);
    expect(targets(read("components/CiChart.tsx"))).toContain("./charts/CiChart.client");
    const wrapper = read("components/charts/CiChart.client.tsx");
    expect(wrapper.startsWith('"use client"')).toBe(true);
    expect(wrapper).toMatch(/ssr:\s*false/);
    expect(targets(wrapper)).toContain("../CiPlot");
    for (const f of ["components/CiChart.tsx", "components/DiffView.tsx"]) {
      expect(targets(read(f))).not.toContain("./CiPlot");
    }
  });
});
