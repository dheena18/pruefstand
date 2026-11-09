# Prüfstand dashboard

Static Next.js site (App Router, `output: "export"`, TypeScript strict, Tailwind) that **renders** the exported run
artefacts (`run.json`, `gate.json`, `slices.json`, case shards, `report.html`). It computes no metric (CLAUDE.md §4).
Source of truth for layout and copy: `docs/design/ui-spec.md`.

## Data flow

```text
runs/<id>/ (VM)  --pruefstand export-dashboard-->  data tree  --DASHBOARD_DATA_DIR-->  pnpm build  -->  out/
                    sanitise_run, evidence masking   runs/ cases/ labels.json        validate -> next build -> csp
                                                     manifest.json
```

`DASHBOARD_DATA_DIR` is required (a fixture set, or a checkout of `pruefstand-dashboard-data`). `pnpm build` validates
the tree against `schemas/*.schema.json` (`scripts/dashboard/validate_data.mjs`, ui-spec 2.4), copies it to
`public/data/`, runs `next build`, inserts the per-page CSP `<meta>` (`csp.mjs`) and checks it (`check_csp.mjs`).
Invalid data fails the build; the site has no bad-data state. `NEXT_BASE_PATH` (`/pruefstand` on GitHub Pages) and
`NEXT_PUBLIC_DEMO_API_URL` (enables the Try-it link and `connect-src`) are inlined at build time.

## Fixture sets

`fixtures/populated/` and `fixtures/empty/` are complete data trees; `fixtures/raw/` holds the real tier-1 run
directories they come from. Refresh with `scripts/dashboard/refresh_snapshot.sh <live-e2e run id>...` (download ->
`derive.py` -> `export-dashboard` -> `derive_fixtures.mjs`); `SOURCE.md` of each set records run ids and commands.
`scripts/dashboard/build_set.sh <populated|empty> [--out <name>]` builds a set into `.sets/<name>/`.

## Commands

| Command                                      | What                                                                                             |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `pnpm install`                               | dependencies (`make install` does it)                                                            |
| `pnpm gen:types`                             | TypeScript types from `schemas/` into `src/types/generated/` (CI fails on a diff)                |
| `pnpm gen:licences`                          | `DATA_LICENSES.md` (section 10) -> `src/content/licences.json` and the report's `_licences.json` |
| `pnpm gen:report-tokens`                     | `src/styles/tokens.css` -> the report's `_tokens.css`                                            |
| `pnpm lint` / `pnpm typecheck` / `pnpm test` | ESLint + Prettier, `tsc`, Vitest (`test:coverage`: `src/lib` >= 80 %)                            |
| `make ui-check`                              | lint, typecheck, both set builds, fixture states, Vitest with coverage                           |

Local dev: `DASHBOARD_DATA_DIR=fixtures/populated node ../../scripts/dashboard/build.mjs`, or copy a tree to
`public/data/` and run `pnpm dev`.

## Pages, components, i18n (T8.2a)

| Route                  | Source                                | What                                                                             |
| ---------------------- | ------------------------------------- | -------------------------------------------------------------------------------- |
| `/<locale>/`           | `src/app/[locale]/page.tsx`           | runs list; empty export → `L-EMPTY`                                              |
| `/<locale>/runs/<id>/` | `src/app/[locale]/runs/[id]/page.tsx` | run summary (tier-2 and tier-1 bodies); `_empty` placeholder for an empty export |
| `/<locale>/licences/`  | `src/app/[locale]/licences/page.tsx`  | sources, licences, ODbL offer (`src/content/licences.json`)                      |

- **Data** is read at build time through `src/lib/data.ts` (validated); `src/lib/run-context.ts` bundles a run, its gate,
  labels, baseline entry, `casesPublished` (`cases/<id>/0.json` exists) and the shard-0 failing count.
- **Table rule** (`src/lib/tables.ts`, mirrors `report/tables.py`): `assignTable` / `assignBlock`; `src/lib/summary.ts` lays
  a `GateReport` out in blocks G, A, C, R, J, I, N. No metric is computed; counting and filtering list items only.
- **URL state** (`src/lib/url-state.ts`): `?status&ref&tier&workload&sort&dir&page`. The static HTML is the default view
  (page 1, created desc) rendered as the `<Suspense>` fallback around `RunsList` (the `useSearchParams` reader); after
  hydration `<main data-hydrated="true">` is set. Pagination uses links, so pages work before hydration.
- **Table rule for narrow screens**: `DataTable` renders a table in a focusable, labelled scroll region from 640 px and a
  card list below (CSS switches them; no inline styles).
- **i18n**: `src/i18n/{de,en}.json` (flat keys, ICU `{n}` / plural), `src/lib/i18n.ts`. Data labels: en from
  `labels.json`, de from `metric.` / `cause.` / `rule.` / `info_reason.` keys (`src/lib/labels.ts`). Dates and numbers
  per ui-spec §10.1–§10.2 (`src/lib/format.ts`). `infra_error` is never rendered; only whether it is set is read.
- **Types** come only from `src/types/generated/`; `src/lib/types.ts` re-exports the ones the pages use.

## Diff, Slices, Cases (T8.2b)

| Route                                 | Source                                               | What                                                                                |
| ------------------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `/<locale>/runs/<id>/diff/`           | `src/app/[locale]/runs/[id]/diff/page.tsx`           | gated pairs (block G) as dot-and-whisker rows; tier 1: notice and block R, no chart |
| `/<locale>/runs/<id>/slices/`         | `src/app/[locale]/runs/[id]/slices/page.tsx`         | slice bars: Gated / Informational (tier 1: Checks / Reported / Informational)       |
| `/<locale>/runs/<id>/cases/`          | `src/app/[locale]/runs/[id]/cases/page.tsx`          | cases list over the sharded case files, filter / search / paging in the URL, detail |
| `/<locale>/runs/<id>/cases/<caseId>/` | `src/app/[locale]/runs/[id]/cases/[caseId]/page.tsx` | static page of a failing case (same `CaseDetail` as the panel)                      |

- **Static params** (UI12-08): diff and slices exist for runs with `gate.json` and `no_baseline == false`; the cases list for
  runs with `cases/<id>/0.json` (the newest 20); case pages for the failing cases of shard 0. An empty set gives the
  `_empty` placeholder (`empty.runs` / `empty.cases`, `noindex`); `dynamicParams = false`. `src/lib/run-pages.ts`.
- **Charts** (D664): `CiChart` / `SliceChart` = `ChartShell` (figure, caption, always-present table, toggle) around a
  `charts/*.client.tsx` wrapper that lazy-loads `CiPlot` / `SlicePlot` with `ssr: false`. SVG attributes only, no `style`.
- **Query-driven pages**: the static HTML is the default view (`<Suspense>` fallback); `DiffQuery`, `SlicesQuery`,
  `CasesList` apply `?sort&slice&page`, `?d_<section>&m_<section>`, `?failing&tenant&category&lang&perturbation&q&page&case`
  after hydration (`src/lib/{diff,slices,cases-state}.ts`, `use-query.ts`).
- **Case sharding** (`src/lib/cases.ts`, D665, D668): shard 0 holds every failing case (R4). The browser loads shard 0, then
  shards 1+ in parallel (`ShardStore`), each with `SHARD_TIMEOUT_MS = 15000`, a hand-written validation and a Retry
  (`C-LOADING`, `C-SHARD-ERROR`). Totals are the sum of the loaded shard lengths, never `n_cases`. All runtime URLs come
  from `dataUrl()` (`src/lib/data-url.ts`) and therefore sit below `basePath`.
- **Case detail** (`CaseDetail`, `AnswerPair`, `CitationList`, `ChunkCard`, `TenantBadge`): text only (`lang={case.lang}`,
  `pre-wrap`), a foreign-tenant chunk reads "⚠ LEAK", the chunk text is never published.

## Manual accessibility check (M6, M7)

NVDA + Firefox and VoiceOver + Safari through navigation and Try it in both locales; record the result here.
