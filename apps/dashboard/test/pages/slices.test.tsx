import { readFileSync } from "node:fs";
import path from "node:path";

import { render, screen, within } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import SlicesPage, {
  generateMetadata,
  generateStaticParams,
} from "@/app/[locale]/runs/[id]/slices/page";
import { SlicesView } from "@/components/SlicesView";

import { IDS, POPULATED, indexOf, labelsOf, sliceRow } from "../fixtures";
import { dataWithIndex } from "../pages-helpers";

const query = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/en/runs/x/slices/",
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

const section = (container: HTMLElement, id: string) =>
  container.querySelector(`section[data-section='${id}']`) as HTMLElement;

async function view(
  rows: ReturnType<typeof sliceRow>[],
  q = "",
  tier1 = null as null | { splits: string[]; n: number },
) {
  const labels = await labelsOf();
  return render(
    <SlicesView
      locale="en"
      labels={labels}
      rows={rows}
      stack={tier1 ? "live" : "a40"}
      tier1={tier1}
      query={q}
    />,
  );
}

describe("Slices, tier 2 (synthetic rows)", () => {
  const rows = [
    sliceRow({ value: "kanzlei_mueller" }),
    sliceRow({
      value: "stadtwerke_sued",
      status: "insufficient_data",
      n_clusters: 22,
      mean_diff: null,
    }),
    sliceRow({
      dimension: "category",
      value: "compound_split",
      gated: false,
      kind: "informational",
      notable: true,
      status: "pass",
      baseline_mean: 0.81,
      candidate_mean: 0.63,
      mean_diff: -0.18,
    }),
    sliceRow({
      dimension: "category",
      value: "typo",
      gated: false,
      kind: "absolute",
      informational_reason: "judge_drift",
      max_value: 0.02,
    }),
  ];
  it("gated and informational are separate sections; informational is labelled 'does not block'", async () => {
    const { container } = await view(rows, "d_gated=tenant&d_informational=category");
    await screen.findAllByRole("img");
    const g = section(container, "gated");
    const i = section(container, "informational");
    expect(within(g).getByRole("heading", { level: 2 })).toHaveTextContent("Gated slices");
    expect(within(i).getByRole("heading", { level: 2 })).toHaveTextContent(
      "Informational, does not block",
    );
    expect(g).toHaveTextContent("kanzlei_mueller");
    expect(g).not.toHaveTextContent("compound_split");
    expect(i).toHaveTextContent("compound_split");
    expect(i).toHaveTextContent("notable");
    expect(i).toHaveTextContent("judge drift"); // an absolute row with a reason is Informational
    expect(i).not.toHaveTextContent(/PASS|FAIL/);
    const shown = container.querySelectorAll("tbody tr").length;
    expect(shown).toBe(4); // every row once
  });
  it("an INSUFFICIENT row shows its clusters text", async () => {
    const { container } = await view(rows, "d_gated=tenant");
    await screen.findAllByRole("img");
    expect(section(container, "gated")).toHaveTextContent("insufficient (22 clusters)");
  });
  it("no slice rows at all → EmptyState text; an unknown dimension in the URL falls back to the default", async () => {
    const empty = await view([]);
    expect(empty.container).toHaveTextContent("No slices for this dimension.");
    empty.unmount();
    const { container } = await view(rows, "d_gated=lang&m_gated=zzz");
    await screen.findAllByRole("img");
    expect(section(container, "gated")).toHaveTextContent("kanzlei_mueller");
  });
  it("selectors list the section's dimensions and metrics; they are labelled", async () => {
    const { container } = await view(rows);
    const g = section(container, "gated");
    expect(within(g).getByLabelText("Dimension")).toBeInTheDocument();
    expect(within(g).getByLabelText("Metric")).toBeInTheDocument();
    expect(within(g).getByLabelText("Dimension").querySelectorAll("option")).toHaveLength(1);
  });
});

describe("Slices, tier 1 (F-T1, UI11-01)", () => {
  it("Tier1Notice, then exactly three sections in order; checks = error_rate with status word", async () => {
    const { container } = render(await SlicesPage(params(IDS.tier1)));
    await screen.findAllByRole("img");
    expect(screen.getByRole("note")).toBeInTheDocument();
    const ids = [...container.querySelectorAll("section[data-section]")].map((s) =>
      s.getAttribute("data-section"),
    );
    expect(ids).toEqual(["checks", "reported", "informational"]);
    const checks = section(container, "checks");
    expect(within(checks).getByRole("heading", { level: 2 })).toHaveTextContent("Checks (decide)");
    expect(checks).toHaveTextContent("Error rate");
    expect(checks).toHaveTextContent("PASS");
    const reported = section(container, "reported");
    expect(within(reported).getByRole("heading", { level: 2 })).toHaveTextContent(
      "Reported — does not decide at n = 18",
    );
    expect(reported).not.toHaveTextContent(/PASS|FAIL|WARN/);
    expect(reported).toHaveTextContent("reported in tier 1");
    expect(reported).toHaveTextContent("Injection success");
    expect(reported).toHaveTextContent("injection reported in tier 1");
    const info = section(container, "informational");
    expect(within(info).getByRole("heading", { level: 2 })).toHaveTextContent(
      "Informational, does not block",
    );
    expect(info).not.toHaveTextContent(/PASS|FAIL|WARN/);
  });
  it("de", async () => {
    render(await SlicesPage(params(IDS.tier1, "de")));
    expect(screen.getByRole("note")).toHaveTextContent("Stufe 1 entscheidet nur");
  });
});

describe("static params", () => {
  it("excludes F-NO-BASELINE and ungated runs", async () => {
    const runs = await indexOf();
    const expected = runs
      .filter((r) => r.status !== null && r.no_baseline !== true)
      .map((r) => r.run_id)
      .sort();
    const got = (await generateStaticParams())
      .filter((p) => p.locale === "en")
      .map((p) => p.id)
      .sort();
    expect(got).toEqual(expected);
    expect(got).not.toContain(IDS.noBaseline);
  });
  it("only no-baseline + ungated → [{id: '_empty'}]; renders empty.runs with noindex (UI12-08)", async () => {
    const runs = await indexOf();
    const dir = await dataWithIndex(
      runs.filter((r) => r.run_id === IDS.noBaseline || r.run_id === IDS.notGated),
    );
    process.env["DASHBOARD_PUBLIC_DATA"] = dir;
    try {
      expect((await generateStaticParams()).map((p) => p.id)).toEqual(["_empty", "_empty"]);
      const { container } = render(await SlicesPage(params("_empty")));
      expect(container).toHaveTextContent("No runs exported yet.");
      expect((await generateMetadata(params("_empty"))).robots).toEqual({ index: false });
    } finally {
      process.env["DASHBOARD_PUBLIC_DATA"] = POPULATED;
    }
  });
  it("the page imports no chart module; the chart wrapper is the only importer of the plot (UI11-22)", () => {
    const read = (rel: string) => readFileSync(path.join(__dirname, "../../src", rel), "utf8");
    const targets = (code: string) =>
      [...code.matchAll(/(?:from |import\()"([^"]+)"/g)].map((m) => m[1] as string);
    expect(
      targets(read("app/[locale]/runs/[id]/slices/page.tsx")).some((p) =>
        /Slice(Chart|Plot)/.test(p),
      ),
    ).toBe(false);
    expect(targets(read("components/SliceChart.tsx"))).toContain("./charts/SliceChart.client");
    const wrapper = read("components/charts/SliceChart.client.tsx");
    expect(wrapper.startsWith('"use client"')).toBe(true);
    expect(wrapper).toMatch(/ssr:\s*false/);
    expect(targets(wrapper)).toContain("../SlicePlot");
  });
});
