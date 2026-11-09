import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RunContext } from "@/lib/run-context";
import type { RunManifest, SliceDecision } from "@/lib/types";

import { IDS, decision, gateWith } from "../fixtures";
import { loadFixtureContexts, view } from "../summary-helpers";

const ctxs = loadFixtureContexts();

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

const judgedRow = (over: Partial<SliceDecision> = {}) =>
  decision({
    metric: "faithfulness",
    gated: false,
    informational_reason: "judge_drift",
    baseline_mean: 0.88,
    candidate_mean: 0.85,
    ...over,
  });

describe("tier 2 judged subset (UI13-19, ui-spec §12.3)", () => {
  const tier2 = (run: Partial<RunManifest>, rows: SliceDecision[]): RunContext => {
    const base = ctxs["tier1"] as RunContext;
    const gate = gateWith({ status: "pass", decisions: rows });
    return {
      ...base,
      run: { ...base.run, stack: "a40", judge_mode: "local", ...run },
      gate,
    };
  };
  it("a real tier-2 run with judged_subset shows the note before the judged rows", () => {
    const { container } = view(tier2({ judged_subset: true }, [judgedRow()]));
    const note = container.querySelector(".judged-subset-note") as HTMLElement;
    expect(note).toHaveTextContent("judged subset (150 cases)");
    const table = screen.getByRole("table", { name: "Informational (does not block)" });
    expect(note.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
  it("no note without judged_subset or without judged rows", () => {
    expect(
      view(tier2({ judged_subset: false }, [judgedRow()])).container.querySelector(
        ".judged-subset-note",
      ),
    ).toBeNull();
    const other = judgedRow({
      informational_reason: "applicable_clusters<30",
      metric: "ndcg_at_k",
    });
    expect(
      view(tier2({ judged_subset: true }, [other])).container.querySelector(".judged-subset-note"),
    ).toBeNull();
  });
  it("S-JUDGE-FALLBACK is a tier-2 banner only", () => {
    const t2 = view(tier2({ judge_fallback: true }, []));
    expect(t2.container).toHaveTextContent("fallback judge");
    t2.unmount();
    const base = ctxs["tier1"] as RunContext;
    const t1 = view({ ...base, run: { ...base.run, judge_fallback: true } });
    expect(t1.container).not.toHaveTextContent("fallback judge");
  });
});

describe("tier 1 summary omissions (D656)", () => {
  const reported = (over: Partial<SliceDecision>) =>
    decision({
      gated: false,
      informational_reason: "tier1_deterministic_only",
      result: null,
      ...over,
    });
  const tier1 = (rows: SliceDecision[]): RunContext => {
    const base = ctxs["tier1"] as RunContext;
    return { ...base, gate: gateWith({ status: "pass", decisions: rows }) };
  };
  it("shows only the overall rows of block R", () => {
    const { container } = view(
      tier1([
        reported({ metric: "language_match" }),
        reported({ metric: "language_match", dimension: "tenant", value: "stadtwerke_sued" }),
      ]),
    );
    expect(container.querySelectorAll("tr[data-status]")).toHaveLength(1);
    expect(container).not.toHaveTextContent("tenant=stadtwerke_sued");
  });
  it("a block with only non-overall rows does not vanish: those rows are shown", () => {
    const { container } = view(
      tier1([
        reported({ metric: "language_match", dimension: "tenant", value: "stadtwerke_sued" }),
      ]),
    );
    expect(container).toHaveTextContent("Language match");
    expect(container).toHaveTextContent("tenant=stadtwerke_sued");
  });
  it("an INSUFFICIENT_DATA row is shown once (the line), not also in a table", () => {
    const row = decision({
      metric: "ndcg_at_k",
      status: "insufficient_data",
      n_clusters: 12,
      result: null,
    });
    const { container } = view(tier1([row]));
    expect(container).toHaveTextContent("Insufficient data: nDCG@k (12 clusters)");
    expect(screen.queryByRole("table", { name: "Gated metrics (overall)" })).toBeNull();
    expect(container).not.toHaveTextContent("INSUFFICIENT DATA");
  });
});
