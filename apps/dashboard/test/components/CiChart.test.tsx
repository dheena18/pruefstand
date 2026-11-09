import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CiChart } from "@/components/CiChart";

import { decision, labelsOf } from "../fixtures";

const rows = [
  decision({ metric: "context_recall", status: "fail" }),
  decision({
    metric: "faithfulness",
    status: "pass",
    dimension: "tenant",
    value: "kanzlei_mueller",
  }),
  decision({ metric: "citation_f1", status: "insufficient_data", result: null, n_clusters: 22 }),
];

describe("CiChart", () => {
  it("is a figure with a figcaption; the table alternative is always in the DOM", async () => {
    const labels = await labelsOf();
    const { container } = render(<CiChart locale="en" labels={labels} rows={rows} />);
    expect(container.querySelector("figure")).not.toBeNull();
    expect(container.querySelector("figcaption")).toHaveTextContent("95 % CI");
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(1 + rows.length);
    expect(await screen.findAllByRole("img")).toHaveLength(rows.length);
  });
  it("toggles to the table view and back; no style attribute anywhere", async () => {
    const labels = await labelsOf();
    const { container } = render(<CiChart locale="en" labels={labels} rows={rows} />);
    await screen.findAllByRole("img");
    const fig = container.querySelector("figure") as HTMLElement;
    expect(fig).toHaveAttribute("data-view", "chart");
    screen.getByRole("button", { name: "Show as table" }).click();
    await screen.findByRole("button", { name: "Show as chart" });
    expect(fig).toHaveAttribute("data-view", "table");
    expect(container.querySelector("[style]")).toBeNull();
  });
  it("without a chart (SSR/no JS) the table is the visible content", async () => {
    const labels = await labelsOf();
    const { renderToString } = await import("react-dom/server");
    const html = renderToString(<CiChart locale="en" labels={labels} rows={rows} />);
    expect(html).toContain("<table");
    expect(html).toContain('data-view="table"');
    expect(html).not.toContain('role="img"');
  });
});
