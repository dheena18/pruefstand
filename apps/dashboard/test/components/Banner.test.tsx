import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Banner } from "@/components/Banner";
import { stopReasonText, summaryBanners } from "@/lib/banners";
import type { Locale } from "@/lib/i18n";
import type { RunManifest } from "@/lib/types";

import { IDS, ctxOf, gateWith } from "../fixtures";

async function run(id: string, over: Partial<RunManifest> = {}): Promise<RunManifest> {
  return { ...(await ctxOf(id)).run, ...over };
}

const EVERYTHING = async (locale: Locale) => {
  const base = await run(IDS.tier1, {
    complete: false,
    stop_reason: "budget_exceeded",
    judge_mode: "skipped",
    judge_fallback: true,
    judge_degraded: true,
    judge_drift: true,
  });
  return summaryBanners({
    locale,
    run: base,
    gate: gateWith({ status: "unsupported_config", no_baseline: false, baseline_run_id: "gone" }),
    baselineInIndex: false,
  });
};

describe("summaryBanners (ui-spec §4.2 table)", () => {
  it("emits every banner in table order", async () => {
    const ids = (await EVERYTHING("en")).map((b) => b.id);
    expect(ids).toEqual([
      "S-PARTIAL",
      "S-JUDGE-SKIPPED",
      "S-JUDGE-FALLBACK",
      "S-JUDGE-DEGRADED",
      "S-JUDGE-DRIFT",
      "S-UNSUPPORTED",
      "S-BASELINE-MISSING",
    ]);
  });
  it("S-NOT-GATED for a complete run without a gate; S-NO-BASELINE is an alert and excludes S-BASELINE-MISSING", async () => {
    const r = await run(IDS.tier1, { judge_mode: "github" });
    expect(
      summaryBanners({ locale: "en", run: r, gate: null, baselineInIndex: false }).map((b) => b.id),
    ).toEqual(["S-NOT-GATED"]);
    const nb = summaryBanners({
      locale: "en",
      run: r,
      gate: gateWith({ no_baseline: true, baseline_run_id: null }),
      baselineInIndex: false,
    });
    expect(nb.map((b) => b.id)).toEqual(["S-NO-BASELINE"]);
    render(<Banner items={nb} locale="en" />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "No baseline for this evaluation fingerprint",
    );
  });
  it("maps each stop_reason", async () => {
    const r = await run(IDS.tier1);
    for (const [code, en, de] of [
      ["completed", "completed", "abgeschlossen"],
      ["budget_exceeded", "budget exceeded", "Budget überschritten"],
      ["aborted", "aborted", "abgebrochen"],
    ] as const) {
      expect(stopReasonText("en", { ...r, stop_reason: code })).toBe(en);
      expect(stopReasonText("de", { ...r, stop_reason: code })).toBe(de);
    }
  });
  it("aborted with infra_error → aborted (infrastructure); the detail is never rendered (UI12-16)", async () => {
    const r = await run(IDS.partial, {
      complete: false,
      stop_reason: "aborted",
      infra_error: "tunnel_lost: host cairo-s101lp",
    });
    for (const [locale, text] of [
      ["en", "aborted (infrastructure)"],
      ["de", "abgebrochen (Infrastruktur)"],
    ] as const) {
      const items = summaryBanners({ locale, run: r, gate: null, baselineInIndex: false });
      const { container, unmount } = render(<Banner items={items} locale={locale} />);
      expect(container).toHaveTextContent(text);
      expect(container.innerHTML).not.toContain("tunnel_lost");
      expect(container.innerHTML).not.toContain("cairo-s101lp");
      unmount();
    }
  });
  it("judge drift text is the D253 count text; no banner mentions 0.85, recalibration or run-gate", async () => {
    const texts = (await EVERYTHING("en")).map((b) => b.text);
    expect(texts).toContain(
      "Judge drift detected (5 or more of 50 anchor verdicts changed); judged metrics are informational until the flag clears.",
    );
    const de = (await EVERYTHING("de")).map((b) => b.text).join(" ");
    expect(de).toContain("5 oder mehr von 50 Ankerurteilen geändert");
    for (const text of [...texts, de]) {
      expect(text).not.toMatch(/0\.85|0,85|recalibration|run-gate/);
    }
  });
});

describe("Banner", () => {
  it("shows at most 3 and puts the rest behind a disclosure", async () => {
    const items = await EVERYTHING("en");
    const { container } = render(<Banner items={items} locale="en" />);
    expect(screen.getAllByRole("status")).toHaveLength(items.length);
    const more = container.querySelector("details");
    expect(more).not.toBeNull();
    expect(screen.getByText("4 more notices")).toBeInTheDocument();
    expect(container.querySelectorAll(".banner-zone > .banner")).toHaveLength(3);
  });
  it("renders nothing without banners and has no disclosure for 3 or fewer", () => {
    const { container, rerender } = render(<Banner items={[]} locale="de" />);
    expect(container).toBeEmptyDOMElement();
    rerender(<Banner items={[{ id: "a", severity: "info", text: "x" }]} locale="de" />);
    expect(container.querySelector("details")).toBeNull();
  });
  it("the banner texts of ui-spec §10.4.1 in de", async () => {
    const items = await EVERYTHING("de");
    expect(items[0]?.text).toBe(
      "Unvollständiger Lauf — nicht bewertet (Abbruchgrund: Budget überschritten).",
    );
    expect(items.at(-1)?.text).toBe(
      "Baseline-Lauf gone ist nicht im Export; keine Baseline-Details.",
    );
  });
});
