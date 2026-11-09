import { render } from "@testing-library/react";
import { beforeAll } from "vitest";

import { RunSummaryView } from "@/components/RunSummaryView";
import type { Locale } from "@/lib/i18n";
import type { RunContext } from "@/lib/run-context";

import { IDS, ctxOf } from "./fixtures";

export const view = (ctx: RunContext, locale: Locale = "en", basePath = "") =>
  render(
    <RunSummaryView
      locale={locale}
      ctx={ctx}
      basePath={basePath}
      githubUrl="https://example.org/r"
    />,
  );

/** The real fixture contexts by `IDS` name, loaded once per test file. */
export function loadFixtureContexts(): Record<string, RunContext> {
  const ctxs: Record<string, RunContext> = {};
  beforeAll(async () => {
    for (const [name, id] of Object.entries(IDS)) ctxs[name] = await ctxOf(id);
  });
  return ctxs;
}
