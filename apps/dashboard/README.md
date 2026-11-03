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

## Manual accessibility check (M6, M7)

NVDA + Firefox and VoiceOver + Safari through navigation and Try it in both locales; record the result here.
