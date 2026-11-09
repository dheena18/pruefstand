import { render, screen, within } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SliceChart } from "@/components/SliceChart";

import { labelsOf, sliceRow } from "../fixtures";

const twenty = Array.from({ length: 20 }, (_, i) =>
  sliceRow({ value: `v${String(i).padStart(2, "0")}`, mean_diff: -0.01 * i }),
);

async function show(rows = twenty, props: Partial<Parameters<typeof SliceChart>[0]> = {}) {
  const labels = await labelsOf();
  return render(
    <SliceChart
      locale="en"
      labels={labels}
      rows={rows}
      metric="context_recall"
      dimension="tenant"
      group="gated"
      {...props}
    />,
  );
}

describe("SliceChart", () => {
  it("figure + figcaption, table alternative always present (all values)", async () => {
    const { container } = await show();
    expect(container.querySelector("figure")).not.toBeNull();
    expect(container.querySelector("figcaption")).toHaveTextContent("Context recall");
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(21);
  });
  it("20 values → 12 bars and 'Show all 20 in table'", async () => {
    await show();
    expect(await screen.findAllByRole("img")).toHaveLength(12);
    expect(screen.getByRole("button", { name: "Show all 20 in table" })).toBeInTheDocument();
  });
  it("≤ 12 values: all bars, the plain 'Show as table' button", async () => {
    await show(twenty.slice(0, 5));
    expect(await screen.findAllByRole("img")).toHaveLength(5);
    expect(screen.getByRole("button", { name: "Show as table" })).toBeInTheDocument();
  });
  it("no Δ text when mean_diff is null; Δ text otherwise", async () => {
    const { container } = await show([
      sliceRow({ value: "a", mean_diff: null }),
      sliceRow({ value: "b", mean_diff: -0.05 }),
    ]);
    await screen.findAllByRole("img");
    const rows = container.querySelectorAll(".sliceplot__row");
    expect(rows[0]).toHaveTextContent("0.84 → 0.79");
    const texts = [...rows].map((r) => r.querySelector(".sliceplot__delta")?.textContent ?? null);
    expect(texts.filter((x) => x !== null)).toEqual(["Δ −0.05"]);
  });
  it("gated rows show a status word; informational rows show marker and reason label, no status word", async () => {
    const info = sliceRow({
      value: "compound_split",
      gated: false,
      kind: "informational",
      notable: true,
      informational_reason: "judge_drift",
      status: "pass",
    });
    const { container } = await show([info], { group: "informational" });
    await screen.findAllByRole("img");
    expect(container).toHaveTextContent("notable");
    expect(container).toHaveTextContent("judge drift");
    expect(container).not.toHaveTextContent(/PASS|FAIL|WARN/);
    expect(container.querySelector("[style]")).toBeNull();
  });
  it("gated: an INSUFFICIENT row says insufficient with its clusters; a PASS row shows the word", async () => {
    const { container } = await show([
      sliceRow({ value: "a", status: "insufficient_data", n_clusters: 22, mean_diff: null }),
      sliceRow({ value: "b", status: "pass" }),
    ]);
    await screen.findAllByRole("img");
    expect(container).toHaveTextContent("insufficient (22 clusters)");
    expect(container).toHaveTextContent("PASS");
  });
  it("de: caption and button texts", async () => {
    await show(twenty, { locale: "de" });
    expect(
      await screen.findByRole("button", { name: "Alle 20 als Tabelle zeigen" }),
    ).toBeInTheDocument();
  });
  it("server render: the table, no svg", async () => {
    const labels = await labelsOf();
    const html = renderToString(
      <SliceChart
        locale="en"
        labels={labels}
        rows={twenty}
        metric="context_recall"
        dimension="tenant"
        group="gated"
      />,
    );
    expect(html).toContain("<table");
    expect(html).not.toContain('role="img"');
  });
});
