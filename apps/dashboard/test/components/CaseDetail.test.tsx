import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CaseDetail, type CaseDetailProps } from "@/components/CaseDetail";

import { makeCase } from "../cases-helpers";
import { labelsOf } from "../fixtures";

async function show(over: Partial<CaseDetailProps> = {}) {
  const labels = await labelsOf();
  return render(
    <CaseDetail
      locale="en"
      labels={labels}
      value={makeCase()}
      baseline={{
        state: "found",
        value: makeCase({ answer: "Baseline-Antwort", metric_values: { context_recall: 0.5 } }),
      }}
      hardFails={[]}
      {...over}
    />,
  );
}

describe("CaseDetail", () => {
  it("question and answers carry lang=case.lang and pre-wrap (de and en cases)", async () => {
    for (const lang of ["de", "en"] as const) {
      const c = makeCase({ lang, question: "Line one\nLine two", answer: "A\nB" });
      const { container, unmount } = await show({
        value: c,
        baseline: { state: "found", value: { ...c, answer: "B\nC" } },
      });
      const langs = [...container.querySelectorAll(".case-text")].map((e) =>
        e.getAttribute("lang"),
      );
      expect(langs.length).toBeGreaterThanOrEqual(3);
      expect(new Set(langs)).toEqual(new Set([lang]));
      expect(container.querySelector(".case-text")?.className).toContain("pre-wrap");
      unmount();
    }
  });
  it("a <script> answer is text, never markup", async () => {
    const c = makeCase({ answer: "<script>alert(1)</script>" });
    const { container } = await show({ value: c });
    expect(container.querySelector("script")).toBeNull();
    expect(container).toHaveTextContent("<script>alert(1)</script>");
  });
  it("citations are lang=de chips; none → no citations", async () => {
    await show();
    expect(screen.getByText("§ 622 Abs. 3 BGB")).toHaveAttribute("lang", "de");
    const { container } = await show({ value: makeCase({ citations: [] }) });
    expect(container).toHaveTextContent("no citations");
  });
  it("refused badge and expected refusal text", async () => {
    const { container } = await show({
      value: makeCase({
        refused: true,
        expect_refusal: true,
        answer: "Dazu liegen keine Informationen vor.",
      }),
    });
    expect(screen.getAllByText("Refused").length).toBeGreaterThan(0);
    expect(container).toHaveTextContent("expected: refusal");
  });
  it("an error class replaces the answer; no answer says so", async () => {
    const { container } = await show({ value: makeCase({ error: "TimeoutError", answer: null }) });
    expect(container).toHaveTextContent("Error: TimeoutError");
    const b = await show({ value: makeCase({ answer: null }) });
    expect(b.container).toHaveTextContent("no answer");
  });
  it("metric_status: ok → value, not_applicable → n/a (not applicable), error → error", async () => {
    const c = makeCase({
      metric_values: { context_recall: 1, ndcg_at_k: null, citation_f1: null },
      metric_status: { context_recall: "ok", ndcg_at_k: "not_applicable", citation_f1: "error" },
    });
    await show({ value: c });
    const row = (name: string) => screen.getByText(name).closest("tr") as HTMLElement;
    expect(row("Context recall")).toHaveTextContent("0.50");
    expect(row("Context recall")).toHaveTextContent("1.00");
    expect(row("nDCG@k")).toHaveTextContent("n/a (not applicable)");
    expect(within(row("Citation F1")).getByText("error")).toBeInTheDocument();
  });
  it("S-BASELINE-MISSING: the 'Baseline not exported' panel; base column is –", async () => {
    const { container } = await show({ baseline: { state: "missing" } });
    expect(container.querySelector("[data-state='baseline-missing']")).toHaveTextContent(
      "Baseline not exported",
    );
    expect(screen.getByText("Context recall").closest("tr")).toHaveTextContent("–");
  });
  it("baseline loading shows a placeholder; a baseline error says it could not be loaded", async () => {
    const a = await show({ baseline: { state: "loading" } });
    expect(a.container.querySelector(".skeleton")).not.toBeNull();
    a.unmount();
    const b = await show({ baseline: { state: "error" } });
    expect(b.container).toHaveTextContent("could not be loaded");
  });
  it("this case's hard-fail finding is shown with German evidence", async () => {
    const f = {
      case_id: "law-0001",
      rule: "hard_fail",
      metric: "tenant_leak",
      evidence: "Mandant fremd",
    };
    const { container } = await show({ hardFails: [f] });
    expect(container.querySelector("q")).toHaveAttribute("lang", "de");
    expect(container).toHaveTextContent("Mandant fremd");
  });
  it("chunk cards: leak from retrieved_chunk_tenant_ids (R3)", async () => {
    const c = makeCase({ retrieved_chunk_tenant_ids: ["shared_public", "versicherung_nord"] });
    const { container } = await show({ value: c });
    expect(container.querySelectorAll(".chunk")).toHaveLength(2);
    expect(container.querySelectorAll(".chunk[data-kind='leak']")).toHaveLength(1);
  });
  it("data without chunk tenants: no badges, the leak comes from the tenant_leak finding", async () => {
    const f = {
      case_id: "law-0001",
      rule: "hard_fail",
      metric: "tenant_leak",
      evidence: "fremder Mandant",
    };
    const c = makeCase({ retrieved_chunk_tenant_ids: [] });
    const { container } = await show({ value: c, hardFails: [f] });
    expect(container.querySelector(".tenant-badge")).toBeNull();
    expect(container).toHaveTextContent("⚠ LEAK in this case");
  });
  it("heading level: h2 in the panel, h1 on the case page; the page link only for failing cases", async () => {
    const a = await show({
      value: makeCase({ failing: true }),
      pageHref: "/en/runs/r/cases/law-0001/",
    });
    expect(screen.getByRole("heading", { level: 2, name: "Case law-0001" })).toHaveAttribute(
      "tabindex",
      "-1",
    );
    expect(screen.getByRole("link", { name: /Page/ })).toBeInTheDocument();
    a.unmount();
    await show({ level: 1 });
    expect(screen.getByRole("heading", { level: 1, name: "Case law-0001" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Page/ })).toBeNull();
  });
  it("de labels", async () => {
    const { container } = await show({ locale: "de" });
    expect(container).toHaveTextContent("Fall law-0001");
    expect(container).toHaveTextContent("Abgerufene Abschnitte (nach Rang)");
  });
});
