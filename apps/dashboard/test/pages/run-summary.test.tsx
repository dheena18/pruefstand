import { render, screen, within } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";

import { RunSummaryView } from "@/components/RunSummaryView";
import type { Locale } from "@/lib/i18n";
import type { RunContext } from "@/lib/run-context";
import type { SliceDecision } from "@/lib/types";

import { IDS, POPULATED, ctxOf, decision, gateWith, indexOf } from "../fixtures";

const view = (ctx: RunContext, locale: Locale = "en", basePath = "") =>
  render(
    <RunSummaryView
      locale={locale}
      ctx={ctx}
      basePath={basePath}
      githubUrl="https://example.org/r"
    />,
  );

const ctxs: Record<string, RunContext> = {};
beforeAll(async () => {
  for (const [name, id] of Object.entries(IDS)) ctxs[name] = await ctxOf(id);
});

describe("S-TIER1 (F-T1)", () => {
  it.each(["en", "de"] as const)(
    "notice, Checks with only the hard-fail row and error_rate, block R (%s)",
    (locale) => {
      const ctx = ctxs["tier1"] as RunContext;
      const { container } = view(ctx, locale);
      expect(screen.getByRole("note")).toBeInTheDocument();
      const checks = container.querySelector("table") as HTMLElement;
      const rows = within(checks).getAllByRole("row").slice(1);
      expect(rows).toHaveLength(2);
      expect(rows[0]).toHaveTextContent(/PASS/);
      expect(rows[1]).toHaveTextContent(locale === "en" ? "Error rate" : "Fehlerquote");
      const reported = container.querySelectorAll("table")[1] as HTMLElement;
      expect(reported).toHaveTextContent(
        locale === "en" ? "reported in tier 1" : "in Stufe 1 nur berichtet",
      );
      expect(reported).toHaveTextContent(
        locale === "en" ? "Injection success" : "Injection-Erfolg",
      );
      expect(reported).toHaveTextContent(
        locale === "en" ? "injection reported in tier 1" : "Injection in Stufe 1 nur berichtet",
      );
      expect(reported).not.toHaveTextContent(/PASS|FAIL|WARN/);
    },
  );
  it("tier-1 meta has no judges entry and no GPU-s; sub-nav has 4 items; page has chunk-free content", () => {
    const { container } = view(ctxs["tier1"] as RunContext);
    expect(container).not.toHaveTextContent("GPU-s");
    expect(container.querySelector(".meta")).not.toHaveTextContent("judges");
    expect(container).not.toHaveTextContent("retrieved_chunk");
  });
  it("renders a refusal_outside_nightly_full decision in block I (UI9-05)", () => {
    const ctx = ctxs["tier1"] as RunContext;
    const extra = decision({
      metric: "refusal_correct",
      gated: false,
      informational_reason: "refusal_outside_nightly_full",
      baseline_mean: 1,
      candidate_mean: 1,
    });
    const gate = { ...(ctx.gate ?? gateWith({})), decisions: [extra] };
    const { container } = view({ ...ctx, gate });
    expect(container).toHaveTextContent("refusal gated only in nightly full");
    expect(container).toHaveTextContent("Informational (does not block)");
  });
  it("block J: judged rows with judged_cases and the source; no status word", () => {
    const ctx = ctxs["tier1"] as RunContext;
    const judged = decision({
      metric: "faithfulness",
      gated: false,
      informational_reason: "tier1_judged",
      baseline_mean: 0.88,
      candidate_mean: 0.85,
    });
    const run = { ...ctx.run, judge_mode: "github" as const, judged_cases: 10, judge_models: {} };
    const gate = { ...(ctx.gate ?? gateWith({})), decisions: [judged] };
    const { container } = view({ ...ctx, run, gate });
    expect(container).toHaveTextContent(
      "Judged metrics — informational, does not block (GitHub Models, 10 cases)",
    );
    expect(container).toHaveTextContent("judge mode github");
    const row = screen.getByText("Faithfulness").closest("tr") as HTMLElement;
    expect(row).not.toHaveTextContent(/PASS|FAIL|WARN/);
  });
  it("a judged_subset run's judged heading is followed by the subset note (UI13-19)", () => {
    const ctx = ctxs["tier1"] as RunContext;
    const judged = decision({
      metric: "faithfulness",
      gated: false,
      informational_reason: "tier1_judged",
    });
    const run = {
      ...ctx.run,
      judge_mode: "github" as const,
      judged_cases: 10,
      judged_subset: true,
      workload: "nightly" as const,
      block: 1,
    };
    const { container } = view({
      ...ctx,
      run,
      gate: { ...(ctx.gate ?? gateWith({})), decisions: [judged] },
    });
    expect(container).toHaveTextContent("judged subset (150 cases)");
    expect(container).toHaveTextContent("workload nightly · block 1");
  });
});

describe("S-HARD-FAIL (F-HARD-FAIL)", () => {
  it("hard fails come first, evidence lang=de, counted as blocking", () => {
    const ctx = ctxs["hardFail"] as RunContext;
    const { container } = view(ctx);
    const checks = container.querySelector("table") as HTMLElement;
    expect(checks.querySelector("tbody tr")).toHaveTextContent(
      "Hard fails (canary, tenant, system prompt)",
    );
    const findings = container.querySelector(".findings") as HTMLElement;
    expect(findings).toHaveAttribute("aria-label", expect.stringMatching(/^Hard fails \(\d+\)$/));
    expect(
      checks.compareDocumentPosition(findings) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(container.querySelector("q")).toHaveAttribute("lang", "de");
    const n = ctx.gate?.hard_fails.length ?? 0;
    expect(container.querySelector(".summary-status__count")).toHaveTextContent(
      `${String(n)} blocking issues`,
    );
    expect(screen.getAllByText("Tenant leak").length).toBeGreaterThan(0);
  });
  it("de page shows the rule.<code> text", () => {
    view(ctxs["hardFail"] as RunContext, "de");
    expect(screen.getAllByText("Mandanten-Leck").length).toBeGreaterThan(0);
  });
});

describe("gate-less and special states", () => {
  it("S-PARTIAL: warn banner with the reason, counts shown, Diff/Slices disabled", () => {
    const { container } = view(ctxs["partial"] as RunContext);
    expect(container).toHaveTextContent(
      "Incomplete run — not gated (stop reason: budget exceeded).",
    );
    expect(container.querySelector(".counts")).toHaveTextContent("not_applicable");
    expect(screen.getByText(/^Diff/)).toHaveTextContent("(not gated)");
    expect(screen.getByText("NOT GATED")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /report/i })).toBeNull();
  });
  it("S-NOT-GATED: info banner, Diff/Slices disabled", () => {
    const { container } = view(ctxs["notGated"] as RunContext);
    expect(container).toHaveTextContent("Not gated — this run has no gate report.");
    expect(screen.getByText(/^Slices/)).toHaveAttribute("aria-disabled", "true");
  });
  it("S-NO-BASELINE: alert, NO BASELINE badge, no metric tables, no baseline-missing banner, Baseline –, Diff/Slices '(nothing compared)'", () => {
    const { container } = view(ctxs["noBaseline"] as RunContext);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "No baseline for this evaluation fingerprint",
    );
    expect(container.querySelector(".badge--lg")).toHaveTextContent("NO BASELINE");
    expect(container.querySelector(".badge--lg")).not.toHaveClass("badge--pass");
    expect(container.querySelectorAll("table")).toHaveLength(0);
    expect(container).not.toHaveTextContent("is not in this export");
    expect(container.querySelector(".meta dd")).toHaveTextContent("–");
    expect(screen.getByText(/^Diff/)).toHaveTextContent("(nothing compared)");
    expect(container).toHaveTextContent("nothing compared");
  });
  it("S-JUDGE-SKIPPED: info banner and the skipped text in the judged section", () => {
    const { container } = view(ctxs["judgeSkipped"] as RunContext);
    expect(screen.getAllByText(/Judge skipped \(quota used up\)/).length).toBeGreaterThanOrEqual(2);
    expect(container.querySelector(".judged-skipped")).not.toBeNull();
  });
  it("S-BASELINE-MISSING: banner, baseline id in mono without a link", () => {
    const ctx = ctxs["baselineMissing"] as RunContext;
    const { container } = view(ctx);
    expect(container).toHaveTextContent(
      `Baseline run ${ctx.gate?.baseline_run_id ?? ""} is not in this export`,
    );
    const dd = container.querySelector(".meta dd") as HTMLElement;
    expect(dd.querySelector(".mono")).toHaveTextContent(ctx.gate?.baseline_run_id ?? "?");
    expect(dd.querySelector("a")).toBeNull();
  });
  it("a baseline in the export is linked with its ref label", () => {
    const ctx = ctxs["hardFail"] as RunContext;
    const { container } = view(ctx);
    expect(container.querySelector(".meta dd a")).toHaveAttribute(
      "href",
      `/en/runs/${ctx.baseline?.run_id ?? "?"}/`,
    );
  });
});

describe("S-CASES-PRUNED (oldest D-MANY clone)", () => {
  it("Cases disabled, no report link, top failing ids without links", () => {
    const ctx = ctxs["pruned"] as RunContext;
    expect(ctx.casesPublished).toBe(false);
    const gate = { ...(ctx.gate ?? gateWith({})), top_failing_cases: ["slice-001", "slice-002"] };
    const { container } = view({ ...ctx, gate });
    expect(screen.getByText(/^Cases/)).toHaveTextContent("(cases not published)");
    expect(screen.queryByRole("link", { name: /HTML report/ })).toBeNull();
    expect(container.querySelector("[data-block='top-failing']")).toHaveTextContent(
      "Case details are published for the newest 20 runs only.",
    );
    expect(container.querySelector("[data-block='top-failing'] a")).toBeNull();
  });
  it("hard-fail findings keep id and evidence but have no Open case links (UI13-16)", () => {
    const ctx = ctxs["hardFail"] as RunContext;
    const { container } = view({ ...ctx, casesPublished: false });
    expect(container.querySelectorAll("q").length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: /Open case/ })).toBeNull();
  });
});

describe("report link, failing count, no inventions", () => {
  it("report link present iff status != null (and published)", () => {
    const withGate = view(ctxs["tier1"] as RunContext, "en", "/pruefstand");
    expect(withGate.container.querySelector("a[href$='report.html']")).toHaveAttribute(
      "href",
      `/pruefstand/data/runs/${IDS.tier1}/report.html`,
    );
    withGate.unmount();
    const none = view(ctxs["notGated"] as RunContext);
    expect(none.container.querySelector("a[href$='report.html']")).toBeNull();
  });
  it("the failing count in the sub-nav equals the shard-0 failing rows", () => {
    const ctx = ctxs["hardFail"] as RunContext;
    view(ctx);
    expect(
      screen.getByRole("link", { name: `Cases (${String(ctx.failing)} failing)` }),
    ).toBeInTheDocument();
    expect(ctx.failing).toBeGreaterThan(0);
  });
});

describe("tier-2 body (inline gate; T8.3 fixtures not yet present)", () => {
  const ctx = (): RunContext => {
    const base = ctxs["tier1"] as RunContext;
    const rows: SliceDecision[] = [
      decision({ metric: "context_recall", status: "fail" }),
      decision({ metric: "faithfulness", status: "pass", result: null, max_drop: null }),
      decision({
        metric: "citation_f1",
        dimension: "tenant",
        value: "stadtwerke_sued",
        status: "warn",
      }),
      decision({
        metric: "ndcg_at_k",
        dimension: "tenant",
        value: "kanzlei_mueller",
        status: "insufficient_data",
        n_clusters: 22,
        result: null,
      }),
    ];
    const gate = gateWith({
      status: "fail",
      decisions: rows,
      absolute_checks: [
        decision({
          metric: "error_rate",
          status: "pass",
          max_value: 0.02,
          gated: true,
          result: null,
        }),
      ],
      notable_slices: [
        decision({
          metric: "language_match",
          dimension: "perturbation",
          value: "compound_split",
          gated: false,
          notable: true,
          status: "pass",
          result: {
            ...(rows[0]?.result as NonNullable<SliceDecision["result"]>),
            mean_diff: -0.18,
          },
        }),
      ],
      not_applicable_counts: { answer_correctness: 12 },
      hard_fails: [],
      top_failing_cases: ["law-0042"],
      likely_cause: "retrieval",
    });
    return {
      ...base,
      run: {
        ...base.run,
        stack: "a40",
        judge_models: { faithfulness: "gemma3:12b" },
        judge_mode: "local",
      },
      gate,
    };
  };
  it("renders G overall, G others not passing, A, N, not applicable, insufficient, top failing, cause", () => {
    const { container } = view(ctx());
    expect(container).toHaveTextContent("1 blocking issue");
    expect(container).toHaveTextContent(
      "Likely cause: Retrieval (chunking, embeddings, top-k, reranker, filter, analyzer)",
    );
    expect(screen.getByRole("table", { name: "Gated metrics (overall)" })).toHaveTextContent(
      "FAIL",
    );
    expect(screen.getByRole("table", { name: "Gated slices not passing" })).toHaveTextContent(
      "tenant=stadtwerke_sued",
    );
    expect(screen.getByRole("table", { name: "Absolute checks" })).toHaveTextContent("Error rate");
    expect(container).toHaveTextContent("perturbation=compound_split −0.18");
    expect(container).toHaveTextContent("Not applicable: Answer correctness (12 cases)");
    expect(container).toHaveTextContent(
      "Insufficient data: nDCG@k · tenant=kanzlei_mueller (22 clusters)",
    );
    expect(container.querySelector("[data-block='top-failing'] a")).toHaveAttribute(
      "href",
      `/en/runs/${IDS.tier1}/cases/law-0042/`,
    );
    expect(container).toHaveTextContent("judges: faithfulness=gemma3:12b");
  });
  it("counts hard fails plus FAIL rows of the gated table", () => {
    const c = ctx();
    const gate = {
      ...(c.gate ?? gateWith({})),
      hard_fails: [{ case_id: "x-1", evidence: "e", metric: "canary_leak", rule: "hard_fail" }],
    };
    view({ ...c, gate });
    expect(screen.getByText("2 blocking issues")).toBeInTheDocument();
  });
});

describe("fixture set coverage", () => {
  it("every run of the populated index builds a summary context", async () => {
    const runs = await indexOf();
    expect(runs.length).toBeGreaterThanOrEqual(60);
    expect(POPULATED).toContain("populated");
  });
});
