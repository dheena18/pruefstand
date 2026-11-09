import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilterBar } from "@/components/FilterBar";
import { LicenceNotice } from "@/components/LicenceNotice";
import { Pagination } from "@/components/Pagination";
import { RunMetaBlock } from "@/components/RunMetaBlock";
import { Tier1Notice } from "@/components/Tier1Notice";
import { DEFAULT_STATE } from "@/lib/url-state";
import { licences } from "@/lib/site";

import { IDS, ctxOf, indexOf } from "../fixtures";

describe("Tier1Notice", () => {
  it("is a role=note with the split and case count", () => {
    render(<Tier1Notice locale="en" splits={["smoke_live"]} n={20} />);
    expect(screen.getByRole("note")).toHaveTextContent("(smoke_live, 20 cases)");
  });
});

describe("Pagination", () => {
  const hrefFor = (n: number) => `/de/?page=${String(n)}`;
  it("marks the current page and links the neighbours", () => {
    render(<Pagination locale="en" page={2} pages={3} hrefFor={hrefFor} />);
    expect(screen.getByRole("navigation", { name: "Pages" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "2" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /Previous/ })).toHaveAttribute("href", "/de/?page=1");
    expect(screen.getByRole("link", { name: /Next/ })).toHaveAttribute("href", "/de/?page=3");
  });
  it("disables Previous on page 1 and renders nothing for one page", () => {
    const { container, rerender } = render(
      <Pagination locale="en" page={1} pages={3} hrefFor={hrefFor} />,
    );
    expect(screen.queryByRole("link", { name: /Previous/ })).toBeNull();
    rerender(<Pagination locale="en" page={1} pages={1} hrefFor={hrefFor} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("FilterBar", () => {
  it("has labelled controls, an aria-live count and reports changes", () => {
    const onChange = vi.fn();
    const { container } = render(
      <FilterBar
        locale="en"
        state={DEFAULT_STATE}
        refs={["main", "pr-62"]}
        onChange={onChange}
        count="3 results"
      />,
    );
    expect(container.querySelector("[aria-live='polite']")).toHaveTextContent("3 results");
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "no_baseline" } });
    expect(onChange).toHaveBeenCalledWith({ status: "no_baseline" });
    expect(screen.getByRole("option", { name: "NO BASELINE" })).toBeInTheDocument();
    expect(screen.getByLabelText("Ref")).toHaveTextContent("pr-62");
  });
});

describe("RunMetaBlock", () => {
  it("tier 1: no GPU-s, no judges entry, judge mode github; baseline linked when exported", async () => {
    const ctx = await ctxOf(IDS.tier1);
    const index = await indexOf();
    const baseline = index.find((r) => r.run_id === ctx.gate?.baseline_run_id) ?? null;
    const { container } = render(
      <RunMetaBlock
        locale="en"
        run={ctx.run}
        baselineRunId={ctx.gate?.baseline_run_id ?? null}
        baseline={baseline}
        githubUrl="https://example.org/r"
      />,
    );
    expect(container).not.toHaveTextContent("GPU-s");
    expect(container).not.toHaveTextContent("judges");
    expect(container).toHaveTextContent("judge mode skipped");
    expect(container).toHaveTextContent("smoke_live");
    expect(container).toHaveTextContent("workload pr");
  });
  it("baseline – when null, mono id without a link when not exported", async () => {
    const ctx = await ctxOf(IDS.tier1);
    const { container, rerender } = render(
      <RunMetaBlock locale="en" run={ctx.run} baselineRunId={null} baseline={null} githubUrl="" />,
    );
    expect(container.querySelector("dd")).toHaveTextContent("–");
    rerender(
      <RunMetaBlock
        locale="en"
        run={ctx.run}
        baselineRunId="20260101T000000-abcdef"
        baseline={null}
        githubUrl=""
      />,
    );
    expect(container.querySelector("dd .mono")).toHaveTextContent("20260101T000000-abcdef");
    expect(container.querySelector("dd:nth-of-type(1) a")).toBeNull();
  });
  it("tier 2: GPU-s shown, judges listed, nightly block and tokens sum", async () => {
    const ctx = await ctxOf(IDS.tier1);
    const run = {
      ...ctx.run,
      stack: "a40" as const,
      workload: "nightly" as const,
      block: 1,
      judge_models: { faithfulness: "gemma3:12b" },
      cost: {
        ...ctx.run.cost,
        gpu_seconds: 2100,
        prompt_tokens: 3_000_000,
        completion_tokens: 1_100_000,
      },
    };
    const { container } = render(
      <RunMetaBlock locale="de" run={run} baselineRunId={null} baseline={null} githubUrl="" />,
    );
    expect(container).toHaveTextContent("~2.100 GPU-s");
    expect(container).toHaveTextContent("Workload nightly · Block 1");
    expect(container).toHaveTextContent("Judges: faithfulness=gemma3:12b");
    expect(container).toHaveTextContent("4,1 M Tokens");
  });
});

describe("LicenceNotice", () => {
  it("compact is the attribution line in the page locale", () => {
    const { container } = render(
      <LicenceNotice locale="en" licences={licences} variant="compact" />,
    );
    expect(container).toHaveTextContent("Questions derived from GermanQuAD/GermanDPR");
  });
  it("the shown-here cell has accessible text, not only a check mark", () => {
    const { container } = render(<LicenceNotice locale="en" licences={licences} />);
    expect(container.querySelector("td .sr-only")).toHaveTextContent(/^(yes|no)$/);
  });
  it("full lists every source and the ODbL offer, not MEMERAG", () => {
    const { container } = render(<LicenceNotice locale="de" licences={licences} />);
    for (const source of licences.sources) expect(container).toHaveTextContent(source.name);
    expect(container).toHaveTextContent("shared under ODbL on request");
    expect(container).not.toHaveTextContent(/MEMERAG/i);
  });
});
