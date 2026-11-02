# Prüfstand UI spec (dashboard, Try it, HTML report, PR comment)

Status: **v6, round 13 resolution applied** (`docs/planning/reviews/round13-resolution.md` P1.2, P4.2,
P5.1–P5.5; findings `round13-ui.md` UI13-01…UI13-20). v5 applied round 12 (`round12-resolution.md` N5,
N6.1, N6.5, N6.6; findings `round12-ui.md` UI12-01…UI12-20). v4 applied round 11
(`round11-resolution.md` Y7.1–Y7.5; findings `round11-ui.md` UI11-01…UI11-23). v3 applied round 9 (`round9-resolution.md` X1.2, X5.1–X5.6,
X2.8, X3.11, X3.14; findings `round9-ui.md` UI9-01…UI9-25, incl. the round-8 half-fixes UI-13, UI-15,
UI-20, UI-26). v2 applied round 8 (W5, W1.3, W1.4, W3.3, W3.6, W3.9; UI-01…UI-28). Source of truth for
the UI (W5.1). Binding for T1.9, T6.4, T8.1, T8.2a, T8.2b, T8.3, T8.4, T8.5 and T9.2 (sections named in
each prompt's "Read first").

Precedence: on **layout, copy, tokens, states and tests** this file wins over a prompt; on **data
contracts** `docs/architecture/interfaces.md` wins. Field names used here are copied from
interfaces.md §2, §9, §10, §10.1, §16: `RunManifest.judge_mode ∈ {github, local, skipped}`,
`judge_fallback` (tier 2 only), `judge_degraded`, `judge_drift`, `judged_cases`, `cost.*`;
`SliceDecision.gated`, `max_drop`, `max_value`, `n_clusters`, `informational_reason`;
`GateReport.baseline_run_id: RunId | None`, `not_applicable_counts`, `no_baseline`;
`RetrievedChunk.used_in_prompt`; and the typed models of `core.models.dashboard` (X5.3): `RunIndexEntry`
(incl. `no_baseline`), `DashboardRunIndex`, `DashboardSliceRow`, `DashboardSlices`, `DashboardCase`,
`DashboardCases`, `LabelsDocument`. Every one has an exported JSON Schema and a generated TS type. If
interfaces.md names a field differently, interfaces wins and this file is fixed in the same PR.

Rules this spec does not change: the dashboard never computes metrics (ADR-0011); TS types come only
from `src/types/generated/`; all text renders as text (no `dangerouslySetInnerHTML`); public data is
sanitised (no chunk text, canaries masked, held-out cases dropped).

Changes v5 → v6 (round 13):
- **Data tree pruning** (P5.1, UI13-01, UI13-20): `push_dashboard_data` (T6.1) rewrites the **whole**
  published tree from the index on every push (newest 200 runs; shards + `report.html` for the newest
  20), so old data is pruned; the deploy only verifies, it never prunes (§2.3).
- **Pages build id** (P5.5, UI13-05): every Pages build writes `build-id.txt`; the post-deploy smoke
  polls it until it matches, then runs every request with a cache-busting query (§2.1, §14.3). A failed
  provenance check never deploys the placeholder (UI13-09); the docs group is keyed by event (UI13-07);
  rollback has a data case and a code case (UI13-08); empty-index smoke (UI13-17).
- **Demo** (P5.2–P5.4, UI13-02…04, UI13-06, UI13-11, UI13-15): demo-ready = release asset
  `demo-ready.json` written by the new `demo-ready.yml` (`workflow_run` of `release.yml`, so `deploy.yml`
  is dashboard-only); the VM reads it with
  **one** anonymous `releases/latest` call per night and `browser_download_url`; the test reset is
  called from **inside** the container (`docker compose exec`), returns 409 while a generation runs;
  pin and kill switch are dispatch modes (§2.1, §4.6, §14.2).
- **Copy and contract fields**: drift notice = the D253 count rule (§10.4.1, §12.1; UI13-10);
  `RunIndexEntry.block` / `judged_subset` shown in runs list, meta block, PR comment and report
  (§4.1, §4.2, §12.3, §13, §15; UI13-19); `infra_error` is published as its kind only (§4.2; UI13-13);
  pruned runs keep hard-fail evidence without `Open case` links (§4.2; UI13-16); `derive.py`
  `--no-baseline` uses the Python store API (§14.1; UI13-14); no `run-gate` label anywhere (P1.2).

Changes v4 → v5 (round 12):
- **Size cap** (N5.1, UI12-01): the export keeps the newest **200** runs in the index and case shards +
  `report.html` only for the newest **20**; a CI step fails when the assembled Pages site is > 800 MB.
  New state `S-CASES-PRUNED` (§2.3, §2.4 rule 9, §4.2, §6).
- **Pages handshake** (N5.2, UI12-02, UI12-07): `docs.yml` deploys on `workflow_run` of a successful
  `deploy.yml`, with `dashboard-site` taken from `github.event.workflow_run.id`; no dispatch, no run-id
  search. One "last good" rule per artefact (§2.1).
- **Demo** (N5.3, N5.4, UI12-03, UI12-04, UI12-10–12): the VM deploys the public GHCR image by digest
  (no artefact download, no token). Try-it tests reset the e2e instance before each of the 8
  combinations through the loopback-only `POST /v1/_test/reset` (`DEMO_TEST_RESET=1`) (§4.6, §14.2;
  v6: called from inside the container, P5.4).
- **`basePath` in the required PR check** (N5.5, UI12-05, UI12-06): job `basepath-smoke` builds with
  `NEXT_BASE_PATH=/pruefstand` and runs a Playwright smoke at `/pruefstand/` (§14.2, §14.3).
- Smaller fixes: per-page `generateStaticParams` and `_empty` for Diff/Slices (§2.1, UI12-08); 404 docs
  link and plain `<a>` for non-app targets (§4.8, §5, UI12-09); `LabelsDocument.hard_fail_rules` is a
  code → en label dict, so `/en` shows rule labels (§10.1, UI12-15, D273); `infra_error` rendering (§4.2, §15, UI12-16); placeholder rows in the matrix (§14.2,
  UI12-18); `.nojekyll` only from the assembly (§2.1, UI12-20); `derive.py` moved to
  `scripts/dashboard/derive.py` (§14.1, N6.5, UI12-17).

Changes v3 → v4 (round 11):
- **Hosting = GitHub Pages** (Y7.1). No response-header files (`headers.json`, `vercel.json` removed). The
  CSP is a per-page `<meta>` with hashes only. `report.html` carries its own `<meta>` CSP, written by
  `render_html` (§7.4; UI11-05, UI11-10, UI11-11).
- **Empty static set builds** through a `_empty` placeholder param (Y7.2, UI11-02, §2.1).
- **Fixture provenance:** `F-PARTIAL`, `F-NO-BASELINE` and `F-JUDGE-SKIPPED` come from real tier-1 runs
  through `derive.py` (v5: `scripts/dashboard/derive.py`). Raw run dirs live under `apps/dashboard/fixtures/raw/`
  (Y7.3, UI11-03, UI11-04, §14.1).
- **Renderers accept `base = None`** (Y7.4, UI11-08). **Tier-1 Slices** has three sections, and the
  Gated one is titled `tier1.checks` because `error_rate` decides (Y7.4, UI11-01, §4.4).
- **Demo** (optional) runs on the VM behind a Cloudflare Tunnel, with a CPU model and in-process limits.
  The Try-it e2e runs nightly on the VM, sequentially, and restarts the container between groups (Y7.5,
  UI11-06, UI11-07, UI11-16, UI11-17, §4.6, §14.2).
- Smaller fixes: static HTML of query pages (§6, UI11-09), PR-comment absolute rows (§11.1, UI11-12),
  judge source label (§10.4.2, UI11-14), offline shard error (§14.2, UI11-18), status filter (§4.1,
  UI11-19), no-baseline Diff/Slices (§2.2, UI11-20), client chart wrappers (§8, UI11-22).

Changes v2 → v3:
- **One static build per fixture set** (`fixtures/populated/`, `fixtures/empty/`), each its own
  Playwright project. Data is validated at build time, and invalid data fails the build. The site has no
  "bad data" panel (`S-BAD-SCHEMA` removed). The error state is the 404 page. `page.route` may only delay
  responses (X1.2, UI9-01, UI9-08).
- Next.js routing tree fixed (X5.1, UI9-02). CSP has no inline scripts of our own, styles come from CSS
  files, and `report.html` has its own policy (X5.2, UI9-03).
- One table rule for every `SliceDecision` (§11.1; X5.4, UI9-05). No-baseline state uses ⚪
  (X5.5, UI9-06). Tier 1 decides on hard fails and `error_rate` only (X5.6, X3.11, UI9-07).
- Typed `DashboardSlices` / `LabelsDocument` (X5.3, UI9-04, UI9-09). Full de/en copy tables
  (UI9-20). Date, ref and token rules (UI9-13, UI9-14). `lang` per case (UI9-12). Try-it fixes
  (UI9-21). Contrast pairs listed (UI9-25).

---

## 1. Principles

1. **Decision first.** Every run page answers "can this ship, and why not?" above the fold: status,
   blocking-issue count, likely cause. Detail is one click away.
2. **Same story everywhere.** PR comment, run summary and HTML report show the same sections in the
   same order with the same labels and number formats (§11). Each `SliceDecision` lands in exactly one
   table by the same rule (§11.1).
3. **Status is never colour alone.** Icon + text + accessible name, everywhere.
4. **Gated vs informational is visually separate.** Informational data sits in its own labelled group
   with "informational, does not block" / "informativ, blockiert nicht".
5. **Say what decided.** A tier-1 run says that only hard fails and the error rate decided. Language,
   citation, refusal and injection results are reported only, and paired statistics are tier 2 (X5.6).
   A judged number from a skipped, fallback, degraded or drifting judge is labelled as such.
6. **Absolute, stable output.** Absolute dates, fixed number formats, deterministic sort orders.
7. **Data keeps its language, chrome follows the locale.** Questions and answers are marked with the
   case's own `lang` (`de` or `en`). Evidence, citations and chunk ids are marked `lang="de"`. Chrome
   follows the locale in the route (`/de` default, `/en`).

---

## 2. Information architecture

### 2.1 Routes and file tree (static export, `basePath` from env, `trailingSlash: true`; X5.1)

```text
src/app/layout.tsx                 pass-through root layout: imports globals.css, returns children (no <html>)
src/app/page.tsx                   root redirect document: <html lang="de">, meta refresh → de/, visible link,
                                   noindex, AppFooter (de). Exported as out/index.html
src/app/not-found.tsx              site 404 document: <html lang="de">, NotFoundView (de) + link to /en/,
                                   AppFooter (de). `next build` exports it as out/404.html
src/app/[locale]/layout.tsx        <html lang={locale}>; generateStaticParams → de, en; dynamicParams = false
src/app/[locale]/not-found.tsx     NotFoundView in the route locale (for notFound() inside the locale tree)
src/app/[locale]/error.tsx         client error boundary (ErrorPanel); Vitest only (§6 X-ERROR)
src/app/[locale]/**/page.tsx       pages below
src/app/[locale]/runs/[id]/layout.tsx   optional (shared sub-nav); exports NO generateStaticParams (UI12-08)
public/theme-init.js               no-flash theme script, loaded with <script src={`${basePath}/theme-init.js`}> (never inline, §7)
```

There is no hand-written `public/404.html`; the export writes the 404 page. There is no
`public/.nojekyll` either: with the Actions deploy Jekyll never runs, and the one `.nojekyll` at the
site root is written by `assemble_pages_site.sh` (T0.4) to document intent (UI12-20). If `next build`
rejects this tree, the task stops and reports (CLAUDE.md §1). It does not switch to middleware or
another layout without a `decisions.md` entry.

**Hosting (Y7.1, D243, N5.2):** GitHub Pages of the public repo, with **one writer**, `docs.yml`, which
deploys **one** artefact. The dashboard is the **site root**: `https://dheena18.github.io/pruefstand/`,
i.e. `basePath` = `NEXT_BASE_PATH` = **`/pruefstand`** in production and in the required PR job
`basepath-smoke` (§14.2), empty in the other local builds and Playwright projects; the mkdocs docs live
at `https://dheena18.github.io/pruefstand/docs/`. **T8.5** produces the dashboard build: `deploy.yml`
fetches and verifies the data, builds `out/` (plus `out/BUILD.json` = `{data_sha, deploy_run_id,
git_sha}`) and uploads it as artefact `dashboard-site`; it dispatches nothing. `docs.yml` (T0.4, deploy
half extended by T8.5) runs on **`workflow_run`** of a successful `deploy.yml` run, checks that run's
provenance, downloads `dashboard-site` from **`github.event.workflow_run.id`** (no dispatch, no run-id
search), puts `out/` at the artefact root and the mkdocs site under `docs/`, fails when the assembled
site is > 800 MB (N5.1), writes **`build-id.txt`** = `<workflow_run.head_sha>-<workflow_run.id>` at
the site root (P5.5), deploys with `actions/deploy-pages` and then runs the post-deploy smoke (§14.3),
which first polls `/pruefstand/build-id.txt` until it equals that value (≤ 10 min), so it never tests
the previous build from the CDN cache (UI13-05). A failed provenance check fails the deploy job
**without deploying**; the placeholder root page is used only when the triggering run is valid but has
no `dashboard-site` (pre-data bootstrap; UI13-09). Pages serves the **site-root** `404.html` for every unknown path with status 404, which is the
dashboard's own `out/404.html` (its links point to `/pruefstand/de/`, `…/en/` and, because `basePath`
is set, the docs home `/pruefstand/docs/`; §4.8). Pages cannot set response headers, so the site sends
no header of ours (§7.4). Every absolute path we write (`theme-init.js` `src`, links, data fetches,
`report.html` links) is prefixed with `basePath` (UI11-11).

**One "last good" rule per artefact (UI12-07):**
- `dashboard-site`: the artefact of the `deploy.yml` run `github.event.workflow_run.id` of the newest
  `docs.yml` run (event `workflow_run`) whose job `post-deploy-smoke` concluded `success` (taken from
  that run's event payload, never from a re-fetched `BUILD.json`; UI13-05). Rollback (runbook §9, T8.5,
  UI13-08): **data-caused** → the owner dispatches `deploy.yml` with that artefact's `BUILD.json`
  `data_sha`; **code-caused** (a regression on `main`) → a revert PR, because a `data_sha` rollback
  rebuilds today's `main` code.
- demo image: the latest release (`GET …/releases/latest`, one anonymous call per night, P5.3) **if** it
  carries the asset `demo-ready.json`, which only a clean leak-probe run of `demo-ready.yml` uploads; the
  digest is the one in `demo-ready.json` and must equal the rag-demo digest of the release asset
  `image-digests.json` (both fetched by `browser_download_url`). A pin written by the `demo-nightly.yml`
  dispatch mode `pin` overrides it until it expires (§4.6, T8.5, UI13-11).

**Static params (UI12-08):** `runs/[id]/layout.tsx` (if any) exports no `generateStaticParams`. Every
page under `runs/[id]/` generates its own params bottom-up: summary → every run in the index; diff and
slices → runs with `gate.json` and `no_baseline == false`; cases list → runs whose case shards are
published (§2.3); case pages → `{id, caseId}` of the failing shard-0 cases of those runs. Each falls back
to `_empty` when its own set is empty.

**Empty dynamic segments (Y7.2, UI11-02):** with `output: "export"`, `next build` rejects a dynamic route
whose `generateStaticParams` returns `[]`. Every dynamic segment below `[locale]` therefore returns
**one placeholder param `_empty`** when it has no real params, with `dynamicParams = false`:
- `runs/[id]` with an empty set for that page → `{id: "_empty"}`. In the empty fixture set this is the
  summary and its children (`diff/`, `slices/`, `cases/`); in a populated set it is Diff/Slices when no
  run was compared (every run no-baseline or ungated) or the cases list when no run has published
  shards. The placeholder renders `EmptyState` `empty.runs` + `empty.runs_hint` and a link to the runs
  list.
- `cases/[caseId]`: each published run without failing cases → `{id: <run id>, caseId: "_empty"}`; no
  published run at all → `{id: "_empty", caseId: "_empty"}`. It renders `EmptyState` `empty.cases` and
  a link to the cases list.
- Placeholder pages carry `<meta name="robots" content="noindex">` and are never linked from any page.
  `validate_data.mjs` rejects a real run id or case id `_empty` (§2.4 rule 8).

| Route (after `/<locale>`) | Page | Generated | Task |
| --- | --- | --- | --- |
| `/` | Runs list | once per locale | T8.2a |
| `/runs/[id]/` | Run summary (tier-1 or tier-2 variant, §4.2) | per run in `runs/index.json` | T8.2a |
| `/runs/[id]/diff/` | Gated diff: every gated (metric × slice) pair (§11.1 block G) with Δ, CI, δ, MDE | per run with `gate.json` and `no_baseline == false` (else `_empty`) | T8.2b |
| `/runs/[id]/slices/` | All slices; gated vs informational groups (tier 1: three sections, §4.4) | per run with `gate.json` and `no_baseline == false` (else `_empty`) | T8.2b |
| `/runs/[id]/cases/` | Cases list over the sharded `cases/<run_id>/<shard>.json`; client-side filter, sort, pagination; detail panel `?case=<case_id>` | per run with published case shards (the newest 20, §2.3; else `_empty`) | T8.2b |
| `/runs/[id]/cases/[caseId]/` | Static case page, **only** for cases with `DashboardCase.failing == true` (§4.5.3) | per run with published case shards | T8.2b |
| `/try/` | Try it (client component). Shows `try.unavailable` when `NEXT_PUBLIC_DEMO_API_URL` is unset at build | once per locale | T8.4 |
| `/licences/` | Sources, licences, attribution, ODbL database offer | once per locale | T8.2a |

Outside the locale tree:

| Path | What |
| --- | --- |
| `/` (`out/index.html`) | Static redirect page to `/de/`: `<meta http-equiv="refresh" content="0; url=de/">` and a visible link "Weiter / Continue". No script and no stored-locale lookup (X5.1). `noindex`; carries the footer |
| `/404.html` | Static 404 in `de` with links to `/de/` and `/en/` (and the docs home when `basePath` is set, §4.8); served by GitHub Pages for every unknown path (unknown run ids, case ids without a static page, unknown locales, Diff/Slices of a no-baseline run, cases of a run without published shards) |
| `/data/runs/<id>/report.html` | Exported HTML report (§13), linked from the run summary (plain `<a>`, §5). Standalone, no dashboard chrome, its own `<meta>` CSP written by `render_html` (§7.4) |

Unknown case ids inside the cases list → inline "not found" (§4.5). `components.md` §4 names `/runs`,
`/diff`, `CaseView`; the routes and components here are canonical (UI-16, updated by T8.2a).

### 2.2 Navigation model

```text
Header (global):  [Prüfstand wordmark → /<locale>/]  Runs  Try it*  Licences      [DE|EN]  [◐ theme]  [GitHub ↗]
                                                     * only when NEXT_PUBLIC_DEMO_API_URL is set at build (UI-25)
Run sub-nav (all /runs/[id]/* pages):   Summary | Diff | Slices | Cases (n failing)
Breadcrumb (run pages):                 Runs › pr-42@d4e5f6a (31.10.2026, 14:02 MEZ)
Footer (global, §4.7):                  attribution line · Sources & licences › · pruefstand vX.Y.Z · data exported <date> · "supports documentation, not a compliance certificate"
```

- Tabs are links (`<nav aria-label>` + `aria-current="page"`), not ARIA tabs.
- Diff and Slices for a run without `gate.json`: `<span aria-disabled="true">` with visible text
  `subnav.not_gated` "(not gated)"; no link (§6).
- Diff and Slices for a run with `no_baseline == true` (UI11-20): `<span aria-disabled="true">` with
  visible text `subnav.nothing_compared` "(nothing compared)"; no link, and no pages are generated (the
  paths return the 404 page; §14.2 Diff row).
- "Cases (n failing)": n = number of `failing == true` rows in shard 0, read at build time (R4 order
  puts every failing case in shard 0). Never `RunIndexEntry.n_cases` (UI9-22).
- `LocaleSwitch` = two links to the **same path and query** in the other locale. It stores nothing;
  the root redirect always goes to `/de/` (X5.1).
- Back to the runs list keeps filter/sort/page (URL query, §4.1).
- Ref label (everywhere: runs list, breadcrumb, meta block, PR comment, report; UI9-14):
  `pr-<pr_number>` if `pr_number` is set, else `git_ref`, else `–`; then `@<git_sha[:7]>` if `git_sha`
  is set. Examples: `pr-42@d4e5f6a`, `main@a1b2c3d`, `–`.

### 2.3 Published data layout (`data/`, written by `pruefstand export-dashboard`, T8.1)

```text
data/runs/index.json                 DashboardRunIndex {schema_version, runs: RunIndexEntry[]}   (interfaces §10.1)
data/runs/<id>/run.json              RunManifest (sanitised)
data/runs/<id>/gate.json             GateReport  (absent for ungated runs)
data/runs/<id>/slices.json           DashboardSlices {schema_version, run_id, rows: DashboardSliceRow[]} (absent without gate.json)
data/runs/<id>/report.html           render_html of sanitised data. Exists exactly when gate.json exists AND the run is
                                     a case-published run (below; W5.3, UI-06, N5.1)
data/cases/<id>/<shard>.json         DashboardCases {schema_version, run_id, shard, n_shards, cases: DashboardCase[]},
                                     ≤ 500 cases, shard = 0…n_shards−1; only for case-published runs (N5.1)
data/labels.json                     LabelsDocument {schema_version, metrics, causes, hard_fail_rules, informational_reasons}
data/manifest.json                   SHA-256 per file (T8.5 verify)
```

Shard order (R4): cases sorted `failing` desc, then `case_id` asc, so shard `0` holds every failing case.

**Size cap (N5.1, UI12-01).** `export-dashboard` (T8.1) keeps the **newest 200 runs** in
`runs/index.json` and their run dirs (order: `created_at` desc, then `run_id` asc), and writes
`cases/<id>/` and `report.html` only for the **newest 20** of them, the *case-published runs*. Older
runs keep `run.json`, `gate.json` and `slices.json` (summary, Diff and Slices still work) but have no
cases list, no case pages and no report link (`S-CASES-PRUNED`, §4.2). The limits are constants in
`pruefstand.core.models.dashboard` (`MAX_INDEX_RUNS = 200`, `MAX_CASE_RUNS = 20`; shared by T8.1's
export, T6.1's `push_dashboard_data` and T8.5's verify script; UI13-01), not CLI flags. **Pruning
(P5.1, owner T6.1):** `push_dashboard_data` clones `pruefstand-dashboard-data`, adds the new run's
files, rebuilds `runs/index.json` from **all** `runs/*/run.json` in the repo (not from the VM's run
dirs), and rewrites the **whole** published tree from that index with the rule above (deletes
`runs/<id>/` beyond 200, `cases/<id>/` and `report.html` beyond 20), plus a fresh `manifest.json`, so
old data is pruned on every push. The dashboard build never prunes: `build-dashboard` builds the
verified tree as is (UI13-20). Bound: 20 × (shards + `report.html` ≤ 2 MB) + 200 × (JSON + ≈ 2 × 4 static pages) stays far
below the 800 MB check that `docs.yml` runs on the assembled site (§2.1); `verify_dashboard_export.py`
(T8.5) also fails on more than 200 index entries or more than 20 case-published runs, and T8.5 records
the measured `out/` and `_pages/` size in its PR.

### 2.4 Build input and build-time validation (X1.2, UI9-01)

- The build reads exactly one data tree, named by `DASHBOARD_DATA_DIR` (required; no default). It is a
  fixture set (`apps/dashboard/fixtures/populated/`, `apps/dashboard/fixtures/empty/`) or, in
  `deploy.yml`, the checkout of `pruefstand-dashboard-data` at the pinned SHA.
- `pnpm build` = `scripts/dashboard/validate_data.mjs "$DASHBOARD_DATA_DIR"` → copy the tree to
  `public/data/` (git-ignored) → `next build` → post-build `scripts/dashboard/csp.mjs` (§7.4) →
  `scripts/dashboard/check_csp.mjs`. `scripts/dashboard/build_set.sh <populated|empty> [--out <name>]`
  runs this with the fixture set and moves `out/` to `apps/dashboard/.sets/<name>/` (default `<name>` =
  the set; git-ignored) for Playwright. `--out` exists because `NEXT_PUBLIC_*` values are inlined at
  build time: the Try-it builds `populated-try` and `populated-try-timeout` are separate outputs of the
  `populated` set with different env (§14.2, UI11-07).
- `validate_data.mjs` fails the build (exit 1, message names the file and the rule) when:
  1. any file fails its JSON Schema (`schemas/*.schema.json`: run_manifest, gate_report,
     dashboard_run_index, dashboard_slices, dashboard_cases, labels) or has an unknown `schema_version`;
  2. an index entry has no `runs/<id>/run.json`, or a run dir is missing from the index;
  3. `gate.json` exists without `slices.json`, or the reverse; a case-published run (rule 9) has
     `gate.json` without `report.html`, or `report.html` without `gate.json`; any other run has a
     `report.html`; `RunIndexEntry.status` is null although `gate.json` exists, or the reverse;
  4. `cases/<id>/` (when present) lacks any shard `0…n_shards−1`, a shard has > 500 cases, or the shards
     disagree on `n_shards`;
  5. a `slices.json` / `cases` `run_id` differs from its directory name;
  6. `manifest.json` (when present) lists a hash that does not match;
  7. the shard order breaks R4 (a `failing` case outside shard 0, or rows not sorted `failing` desc,
     then `case_id` asc);
  8. a run id or case id equals the placeholder `_empty` (§2.1, Y7.2);
  9. the index has more than 200 entries, or `cases/<id>/` exists for a run that is not among the
     newest 20 index entries (`created_at` desc, then `run_id` asc), or is missing for one that is
     (N5.1, §2.3).
- Pages load data through `src/lib/data.ts` with the same runtime validation, so a page can never render
  unvalidated data. The site therefore has **no** "bad data" state. Client-side loads (shards 1+,
  baseline shards) validate again; a failed load or validation shows `C-SHARD-ERROR`.

---

## 3. Global layout

### 3.1 Shell wireframe (desktop ≥ 1024 px)

```text
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ ▣ Prüfstand    Runs   Try it   Licences                          DE|EN   ◐   GitHub ↗    │  header 56 px, sticky
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ [skip link "Zum Inhalt springen" / "Skip to content" — first focusable, visible on focus] │
│   <main id="content">  max-width 1280 px, side padding 24 px (16 px < 640 px)            │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ Fragen abgeleitet aus GermanQuAD/GermanDPR (deepset, CC BY 4.0) und Open Legal Data      │  footer (§4.7)
│ (ODbL 1.0) · Quellen & Lizenzen › · pruefstand vX.Y.Z · Daten exportiert 31.10.2026, 14:00 MEZ │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Mobile (< 640 px)

- Header collapses to wordmark + menu button (`aria-expanded`, `aria-controls`) opening a full-width
  sheet with Runs / Try it / Licences / language / theme. Focus trapped while open; `Esc` closes and
  returns focus to the button.
- Run sub-nav: horizontally scrollable strip (scroll-snap, scroll shadow), active tab scrolled into view.
- Tables: `DataTable` responsive rule (§5).

### 3.3 Breakpoints

| Name | Min width | Layout change |
| --- | --- | --- |
| base | 360 px (minimum supported, tested) | single column, cards, menu sheet |
| `sm` | 640 px | `DataTable` as table in a focusable horizontal scroll region; header nav inline |
| `md` | 768 px | two-column summary header (status block + meta block) |
| `lg` | 1024 px | cases list + detail panel side by side |
| `xl` | 1280 px (tested) | max content width |

No page-level horizontal scroll at 360 px (WCAG 1.4.10); only `DataTable` regions scroll horizontally
(`tabindex="0"`, `role="region"`, `aria-label`).

---

## 4. Pages

Each page: purpose · wireframe · data (→ §15) · states (→ §6 ids) · interactions. Every label in a
wireframe is a §10.4 key; the English text is shown.

### 4.1 Runs list `/<locale>/`

```text
Runs                                         [Status ▾ all] [Ref ▾ all] [Tier ▾ all] [Workload ▾ all]
Showing 1–25 of 62 runs · sorted by Created ↓
┌───────────────┬──────────────────┬──────┬──────────────────────┬──────┬──────────────┬───────┬──────────┬────────┬───────────────┐
│ Status        │ Ref              │ PR   │ Created              │ Tier │ Workload     │ Cases │ Duration │ Cost   │ Flags         │
├───────────────┼──────────────────┼──────┼──────────────────────┼──────┼──────────────┼───────┼──────────┼────────┼───────────────┤
│ ✖ FAIL        │ pr-42@d4e5f6a    │ #42  │ 2026-10-31 14:02 CET │ 2    │ pr           │   790 │ 18m 12s  │ 0 USD  │               │
│ ⊘ NO BASELINE │ pr-43@9f8e7d6    │ #43  │ 2026-10-31 13:10 CET │ 2    │ pr · subset  │   790 │ 17m 40s  │ 0 USD  │               │
│ ⚠ WARN        │ pr-41@0a1b2c3    │ #41  │ 2026-10-30 09:15 CET │ 2    │ pr           │   790 │ 17m 55s  │ 0 USD  │ judge drift   │
│ ✔ PASS        │ pr-40@77aa001    │ #40  │ 2026-10-30 08:01 CET │ 1    │ pr           │    20 │ 14m 03s  │ 0 USD  │ judge skipped │
│ ○ NOT GATED   │ main@a1b2c3d     │ –    │ 2026-10-30 02:00 CET │ 2    │ nightly · b1 │  1500 │ 19m 03s  │ 0 USD  │ incomplete    │
└───────────────┴──────────────────┴──────┴──────────────────────┴──────┴──────────────┴───────┴──────────┴────────┴───────────────┘
                                                                                [‹ Prev] 1 2 3 [Next ›]
```

- Data: `runs/index.json` only, read at **build time** and embedded in the page (no runtime request;
  UI11-09); columns map to `RunIndexEntry` (§15). The "Created"
  header carries no zone; each cell has its own zone (§10.1, UI9-13).
- Tier = `1` when `stack == "live"`, `2` when `stack == "a40"`; the header has a visually hidden
  explanation (`runs.tier_help`).
- Workload (UI13-19) = `RunIndexEntry.workload`, then `· b<k>` (`runs.block_short`) when `block` is set
  (nightly block k: consecutive nightlies test different case blocks against different baselines
  `nightly-b<k>` and must not look comparable), then `· subset` (`runs.judged_subset_short`) when
  `judged_subset` is true (judged numbers cover the 150-case subset only). Copied, never computed.
- Status cell: `no_baseline == true` → `⊘ NO BASELINE` (never INSUFFICIENT, never PASS; X5.5);
  `status == null` → `○ NOT GATED` (never PASS); else the `GateStatus` badge.
- Flags are text (never icons only): `incomplete` (`complete == false`), `judge skipped`
  (`judge_mode == "skipped"`), `judge fallback` (`judge_fallback`), `judge degraded`
  (`judge_degraded`), `judge drift` (`judge_drift`).
- The Ref cell is the only link per row (no extra tab stops).
- Filters, sort and page live in the URL query (UI-24):
  `?status=<v>&ref=<git_ref>&tier=<1|2>&workload=<pr|nightly|bench>&sort=<key>&dir=<asc|desc>&page=<n>`
  with `status ∈ {pass, warn, fail, insufficient_data, unsupported_config, no_baseline, not_gated}`
  and `sort ∈ {created, status, duration, cost}`. A filter change resets `page` to 1, announces the
  count in an `aria-live="polite"` region and never moves focus (WCAG 3.2.2).
- The status filter matches the **rendered status cell** (UI11-19): `no_baseline == true` →
  `no_baseline` first; else `status == null` → `not_gated`; else the lower-case `status`. So
  `?status=insufficient_data` never includes a no-baseline run (`url-state.test.ts` case).
- Sort: Created (default desc), Status (FAIL → NO BASELINE → WARN → UNSUPPORTED CONFIG →
  INSUFFICIENT DATA → PASS → NOT GATED), Duration, Cost; `<button>` inside `<th>` with `aria-sort`.
  Ties break by `run_id` asc. Page size 25.
- < 640 px: card per run: line 1 badge + ref; line 2 created · tier · workload · cases · duration; line 3 flags.

States: `L-POPULATED`; `L-EMPTY` (`empty.runs` + `empty.runs_hint`); `L-FILTERED-EMPTY`
(`empty.filtered` + "Clear filters").

### 4.2 Run summary `/<locale>/runs/[id]/`

Same section order as the PR comment (§12). Variant by `run.json.stack`: `a40` → §4.2.1, `live` →
§4.2.2. Both share the header block and the banner zone. Table membership follows §11.1.

```text
Runs › pr-42@d4e5f6a
┌───────────────────────────────────────────────┬────────────────────────────────────────────┐
│  ✖ FAIL                       [Tier 2]         │ Baseline  main@a1b2c3d  (link if exported) │
│  2 blocking issues                             │ Candidate pr-42@d4e5f6a · PR #42 ↗          │
│  Likely cause: Retrieval (chunking, embed…)    │ core, robust_pr · 790 cases · 18m 12s · 0 USD│
│                                                │ 4.1 M tokens · ~2,100 GPU-s · workload pr   │
│                                                │ (nightly: workload nightly · block 1)       │
│                                                │ judges: <judge_models> · judge mode local   │
└───────────────────────────────────────────────┴────────────────────────────────────────────┘
[ banner zone: max 3 visible, then "n more notices" disclosure ]
Summary | Diff | Slices | Cases (3 failing)
… variant body …
[Open HTML report ↗] [Download]  (only when exported, §4.9)          [View diff →]
```

Meta block rules (UI9-14): tokens = `cost.prompt_tokens + cost.completion_tokens` in §10.2 format (the
same sum as the PR comment and the report); GPU-s = `cost.gpu_seconds`, shown only when
`stack == "a40"`; cases = `run.json.n_cases` (this is the run size, not the exported case count);
workload = `workload`, then ` · block <k>` (`summary.block`) when `run.json.block` is set (UI13-19).
When `run.json.judged_subset` is true, the judged heading (block J, `summary.judged`) is followed by
`summary.judged_subset` "judged subset (150 cases)" (`{n}` = 150, the fixed subset size, D199), so the judged numbers are never read as covering
`n_cases`.

Baseline line (UI11-08): `baseline_run_id == null` → `Baseline –`. `baseline_run_id` set and in the
index → ref label of that run, linked to its summary. Set but not in the index → `baseline_run_id` in
mono, no link (plus `S-BASELINE-MISSING`). Judges line (UI11-14): `judges: <judge_models>` only when
`judge_models` is not empty; tier 1 (`judge_models == {}` by design) shows `judge mode github` only.

Banners (each `role="status"`; `S-NO-BASELINE` `role="alert"`), in this order:

| State id | Condition | Severity | Text key (§10.4) |
| --- | --- | --- | --- |
| `S-PARTIAL` | `run.json.complete == false` | warn | `banner.incomplete` (`{reason}` = `stop_reason.<code>`; `stop_reason == "aborted"` **and** `run.json.infra_error` set → `stop_reason.aborted_infra` "aborted (infrastructure)"; the `infra_error` value itself is never shown; UI12-16, owner T8.2a) |
| `S-NOT-GATED` | no `gate.json`, `complete == true` | info | `banner.not_gated` |
| `S-NO-BASELINE` | `gate.json.no_baseline == true` | error, `role="alert"` | `banner.no_baseline` |
| `S-JUDGE-SKIPPED` | `judge_mode == "skipped"` | info | `banner.judge_skipped` |
| `S-JUDGE-FALLBACK` | `judge_fallback == true` (tier 2) | warn | `banner.judge_fallback` |
| `S-JUDGE-DEGRADED` | `judge_degraded == true` | warn | `banner.judge_degraded` |
| `S-JUDGE-DRIFT` | `judge_drift == true` | warn | `banner.judge_drift` |
| `S-UNSUPPORTED` | `status == UNSUPPORTED_CONFIG` | warn | `banner.unsupported` |
| `S-BASELINE-MISSING` | `gate.json.baseline_run_id` **is not null** and is not in the index | info | `banner.baseline_missing` |

`S-NO-BASELINE` and `S-BASELINE-MISSING` never appear together: with `no_baseline == true`,
`baseline_run_id` is null (X5.5).

Status block: `S-NO-BASELINE` → `StatusBadge` `NO_BASELINE` (`⊘ NO BASELINE`, neutral tokens, ⚪ in
Markdown) + `summary.nothing_compared`, no blocking count. Otherwise the gate status + blocking count.
Blocking count = `len(hard_fails)` + FAIL rows of the Gated table (blocks **G**, **A**/**C**; §11.1).
Counting list items is formatting, not metric computation; T1.9 uses the same rule.

`S-CASES-PRUNED` (N5.1; a run outside the newest 20, so `cases/<id>/` and `report.html` are not
published, §2.3): no banner. `RunSubNav` shows Cases as `<span aria-disabled="true">` with
`subnav.cases_not_published` "(cases not published)"; no report link; "Top failing cases" lists the ids
as text without links, followed by `summary.cases_not_published`; the hard-fail panel (§4.2.1) and the
tier-1 findings list (§4.2.2) keep rule, case id, metric and redacted evidence but have **no**
`[Open case →]` link (the case page does not exist; UI13-16, `HardFailList.test.tsx`). Known at build
time from the absence of `cases/<id>/0.json`.

`infra_error` (D245): rendered only as the `S-PARTIAL` reason above, in the summary and nowhere else
(no runs-list flag, no case page). The dashboard never displays the field's text. The published
`run.json` carries only the **kind** (`"tunnel_lost"`, `"window_exceeded"`, …, the text before `:`):
`sanitise_run` (T6.1) strips the detail, which can carry host names, before anything reaches Pages or
the data repo (UI13-13); `verify_dashboard_export.py` (T8.5) fails on a `:` in it. `report.html` is not
written for such runs (they have no `gate.json`).

#### 4.2.1 Tier-2 body (statistical gate)

```text
Hard fails (1)                                     ← only when present, always first, fail panel
  canary_leak · case law-0107 · metric canary_leak
  Evidence: „… CANARY-**-****** …“  (lang=de, mono, ≤ 200 chars)                [Open case →]

Gated metrics (overall)                            ← block G, dimension overall, status ≠ INSUFFICIENT_DATA
  Metric          Base   PR     Δ (95% CI)             δ      MDE    Status
  Context recall  0.86   0.77   −0.09 (−0.12, −0.06)   0.05   0.06   ✖ FAIL
  Faithfulness    0.91   0.90   −0.01 (−0.03, +0.01)   0.05   0.07   ✔ PASS

Gated slices not passing                           ← block G, other dimensions, status ∉ {PASS, INSUFFICIENT_DATA}
Absolute checks                                    ← block A: Metric · Value · Max · Status
Informational (does not block)                     ← block I: Metric · Base · PR · Δ · Reason (label from labels.json)
Notable slice drops (informational, does not block): perturbation=compound_split −0.18, …   ← block N, notable only
Not applicable: answer_correctness (12 cases)
Insufficient data: Context recall · tenant=stadtwerke_sued (22 clusters)                  ← block G, INSUFFICIENT_DATA
Top failing cases: law-0042, law-0107, xl-0013     (links to static case pages)
```

δ = `SliceDecision.max_drop`; Max = `SliceDecision.max_value` (W5.2); `null` → "–" with visually hidden
"no threshold in policy". MDE on every gated row (W3.6). Δ in block I = `result.mean_diff` when
`result` is present, else "–". Insufficient clusters = `SliceDecision.n_clusters`.

#### 4.2.2 Tier-1 body (hard fails + error rate decide, the rest is reported; X5.6, X3.11)

```text
ℹ Tier 1 decides on hard fails and the error rate only (smoke_live, 20 cases).
  Language, citation, refusal and injection results are reported. Paired statistics need ≥ 30 clusters
  and run in tier 2 (pruefstand/gate).

Checks (decide)                     Check · Value · Max · Status          ← hard-fail row + block C
  Hard fails (canary, tenant, system prompt)   0      0     ✔ PASS   (findings listed below when > 0)
  Error rate                                   0.00   0.02  ✔ PASS
Reported — does not decide at n = 20                                     ← block R
  Metric            Base   PR     Δ       MDE    Max    Reported because
  Language match    1.00   0.95   −0.05   0.21   –      reported in tier 1
  Citation F1       0.90   0.90   +0.00   0.24   –      reported in tier 1
  False refusal     0.00   0.00   +0.00   –      –      reported in tier 1
  Injection success 0.00   0.00   –       –      0.02   injection reported in tier 1
Informational (does not block)                                           ← block I (other reasons)
  Refusal correct   1.00   1.00   +0.00   refusal gated only in nightly full
Judged metrics — informational, does not block (GitHub Models, 10 cases) ← block J
  Metric            Base   PR     Δ       Judged cases
  Faithfulness      0.88   0.85   −0.03   10
  — judge_mode == "skipped": banner.judge_skipped text, no numbers
Top failing cases: …
```

Data (all via §11.1): hard-fail row = `len(hard_fails)` with the findings listed under it (rule names
from `labels.json` `hard_fail_rules` (en) / `rule.<code>` (de), §10.1); block C = Checks; block R = Reported, with "Reported because" = the reason label
(`tier1_deterministic_only`, `tier1_injection_reported`, `applicable_clusters<30`); block I = other
Informational rows; block J = Judged, with "Judged cases" = `run.json.judged_cases`. Δ = `result.mean_diff` when `result` is present, else "–"
(never `candidate_mean − baseline_mean` in TS). A tier-1 run never shows FAIL/WARN from a row of
block R, I or J; if the data says otherwise, render it as given (a gate bug, not a UI decision).

### 4.3 Diff `/<locale>/runs/[id]/diff/`

```text
Gated pairs (12 testable · 2 insufficient data)        Sort: [Status ▾] [Δ] [Metric]   Slice: [all ▾]
                                     −0.20     −0.10   −δ   0    +0.05
Context recall · overall      ✖ FAIL   ┊   ├──●──┤     ┊    │      ┊   −0.09 (−0.12, −0.06)  δ 0.05  MDE 0.06
Context recall · tenant=…     ⚠ WARN   ┊      ├───●──┼─┤    │          −0.07 (−0.11, −0.03)  δ 0.05  MDE 0.10
Faithfulness · overall        ✔ PASS   ┊           ┊    ├●┤ │          −0.01 (−0.03, +0.01)  δ 0.05  MDE 0.07
Context recall · tenant=st…   ◌ INSUFFICIENT DATA (22 clusters < 30) — no CI shown
[Show as table]
```

- One row per block-G decision (Gated table, §11.1), INSUFFICIENT_DATA rows included (greyed,
  `n_clusters`). Informational and Notable rows are not on this page. Shared x scale; domain = min/max of `ci_low`, `ci_high`
  and `−max_drop`, padded 10 %. Dashed line at `−max_drop` **per row** (`max_drop` null → no line, row
  text "no threshold"). Solid line at 0.
- `result == null` → "n/a", no bar.
- Sort default: status (FAIL first), then Δ ascending, then metric, then slice; sort and slice filter
  in the URL query (`?sort=status|delta|metric&slice=<dimension>`).
- Tier-1 run (`S-TIER1`): `Tier1Notice` + block R; no chart (nothing is testable at n = 20).
- No-baseline run: no Diff page (§2.2; the path is the 404 page).

### 4.4 Slices `/<locale>/runs/[id]/slices/`

```text
[Gated slices]                                   [Informational — does not block]
Dimension: [tenant] [lang] [perturbed_all]        Dimension: [category] [perturbation] [tags]
Metric: [Context recall ▾]                       Metric: [Context recall ▾]
 kanzlei_mueller    ████████████▏ 0.84 → 0.79 ✔   compound_split  ███████▏ 0.81 → 0.63  ● notable
 stadtwerke_sued    ░░░░░░░░░░    insufficient (22 clusters)
```

- Rows from `slices.json` (`DashboardSlices.rows`, `DashboardSliceRow`, interfaces §10.1). Group by the
  §11.1 table rule: `gated and informational_reason == null` → Gated group; every other row (reason set,
  or `kind == "informational"`) → Informational group, with the reason label when set (X5.3, X5.4).
  Each row appears once. `kind` distinguishes decisions from absolute checks inside a group.
- Marker from `notable`; insufficient text from `n_clusters`; reason label from
  `informational_reason`; threshold from `max_drop` / `max_value`.
- Grouped horizontal bars (baseline hatched, candidate solid) + Δ text (`mean_diff`; null → no Δ text,
  bars and values only); one chart per (group × dimension × metric). Max 12 bars, worst first (status
  order, then `mean_diff` asc, then `value` asc); more → `slices.show_all`.
- Dimension or metric absent → `EmptyState` `empty.slices`.
- Tier-1 run (`S-TIER1`; Y7.4, UI11-01): `Tier1Notice`, then **three** sections in this order. The
  grouping rule above still decides Gated vs Informational; the tier-1 layout only splits the
  Informational group by §11.1 block:
  1. Gated group, titled `tier1.checks` ("Checks (decide)"): block C, in practice `error_rate`. This row
     **decides** and shows its status word.
  2. `tier1.reported` ("Reported — does not decide at n = N"): block R rows (`tier1_deterministic_only`,
     `tier1_injection_reported`, `applicable_clusters<30`) with the reason label, no status word.
  3. Informational group (`slices.informational`): blocks J and I (and N), as in tier 2.
- No-baseline run: no Slices page (§2.2; the path is the 404 page).

### 4.5 Cases

#### 4.5.1 Data loading (W5.3, interfaces §10.1)

1. Shard `0` is read at **build time** for the static parts (failing count, static case pages) and
   fetched at runtime for the list. It carries `n_shards` and (R4 order) every failing case, so the
   default "Failing only" view renders from shard 0 alone.
2. Then shards `1…n_shards−1` load in parallel. Until all are loaded the list header says
   `cases.loading` ("Loading cases: 2 of 3 parts", `aria-live="polite"`, `C-LOADING`); filters other
   than "Failing only" are enabled, and the total is marked `cases.partial`. A failed shard → inline
   `ErrorPanel` (`shard.error`) + Retry for that shard (`C-SHARD-ERROR`); loaded shards stay usable.
   Each shard fetch has a fixed timeout `SHARD_TIMEOUT_MS = 15000` (`src/lib/cases.ts`); a timeout is a
   failed shard.
3. Filter, search (case id and question text), sort and pagination run client-side over the loaded
   `DashboardCase` rows (no metric computation).
4. Baseline answer: same `case_id` in the baseline run's shards (loaded on demand, shard 0 first);
   `baseline_run_id` null, not exported, or exported without case shards (outside the newest 20,
   §2.3) → "Baseline not exported" panel (`S-BASELINE-MISSING`).
5. Totals (UI9-22): "Cases (N)" = sum of loaded shard lengths, followed by `cases.partial` until every
   shard is loaded; "n failing" = `failing == true` rows of shard 0. Never `RunIndexEntry.n_cases`
   (that counts held-out cases the export drops).

#### 4.5.2 Cases list `/<locale>/runs/[id]/cases/`

```text
Cases (790) · 3 failing            Search id/question [______]  [☑ Failing only] [Tenant ▾] [Category ▾] [Lang ▾] [Perturbation ▾]
┌──────────────────────────────────────────────┬───────────────────────────────────────────────────┐
│ ✖ law-0107  kanzlei_mueller · factual · de    │ Case law-0107                [Copy link] [Page ↗] │
│   Wann endet die Probezeit … (lang=de)        │ tenant kanzlei_mueller · factual · de · perturb – │
│ ✖ law-0042  …                                 │ Question (lang = case.lang)                        │
│ ✔ law-0001  …                                 │ ┌ Baseline answer ─────────┐┌ Candidate answer ──┐ │
│ [‹] 1 2 … 32 [›]   (25 per page)              │ │ …                        ││ …  [Refused]       │ │
│                                               │ Citations   § 622 Abs. 2 BGB · Art. 6 DSGVO        │
│                                               │ Metrics     name · base · candidate · status       │
│                                               │ Retrieved chunks (rank order)                      │
│                                               │  #1 chunk_id · [kanzlei_mueller]                   │
│                                               │  #2 chunk_id · [⚠ LEAK versicherung_nord]          │
└──────────────────────────────────────────────┴───────────────────────────────────────────────────┘
```

- ≥ 1024 px: list + detail side by side; < 1024 px: list only; selecting navigates to `?case=<id>` and
  shows the detail full-width with "Back to cases" (focus → detail `<h2>`).
- Default filter "Failing only" when ≥ 1 case has `failing == true`, else all. Sort: `failing` first,
  then `case_id` asc (= shard order). URL query: `?failing=1&tenant=&category=&lang=&perturbation=&q=&page=&case=`.
  Page size 25.
- Rows with `failing == true` show `[Page ↗]` to their static case page; others are detail-only.
- Unknown `?case=` → inline `case.not_found` + link to the list (`C-NOT-FOUND`).

#### 4.5.3 Static case pages `/<locale>/runs/[id]/cases/[caseId]/`

- `generateStaticParams` = cases with `DashboardCase.failing == true` in shard 0 (in
  `top_failing_cases` or any hard fail; bounded by top-N, UI-05). Built from shard 0 at build time.
- Same `CaseDetail` component, full width, breadcrumb `Runs › run › Cases › law-0107`.

#### 4.5.4 Case detail content (`DashboardCase`)

- Question and answers: plain text, `white-space: pre-wrap`, `lang={case.lang}` (UI9-12). `answer ==
  null` → `case.no_answer`; `refused == true` → badge `case.refused`; `expect_refusal == true` → text
  `case.expected_refusal`; `error` (class name only) → `case.error` in place of the answer.
- Citations: `citations` as text chips, `lang="de"`; empty → `case.no_citations`.
- Metrics table: label, base value, candidate value (`metric_values`), candidate `metric_status`
  (`ok` → value, `not_applicable` → `case.na`, `error` → `case.metric_error`). Hard-fail findings of
  this case (`gate.json.hard_fails` with this `case_id`, evidence `lang="de"`) listed above the table.
- Chunks: `ChunkCard` per `retrieved_chunk_ids` entry (rank = index) with `chunk.text_withheld`. Tenant
  from `retrieved_chunk_tenant_ids` at the same index (R3): equal to the case tenant → own badge;
  `shared_public` → shared badge; other → **leak** (`chunk.leak`). Data exported before R3 (empty
  tuple) → no tenant badge; a leak is shown from the case's `tenant_leak` finding (`case.leak_in_case`
  + evidence).

### 4.6 Try it `/<locale>/try/` (T8.4, optional)

**Hosting (Y7.5, UI11-06):** the demo API runs on the TrueNAS VM `pruefstand-exec` as the compose
project `pruefstand-demo` (profile `demo`: Qdrant, llama.cpp CPU generator ≤ 2B Q4, `embed`, rag-demo,
plus a one-shot `index` service on the slice corpus with `canaries.public.json` only). Every service
runs on the VM CPU; none uses the A40 cluster. Only rag-demo publishes a port, on `127.0.0.1:8090`. A
free **Cloudflare Tunnel** (`cloudflared` container on the `--internal` `demo-net` and on `demo-egress`, the only demo container with internet, P2.2; token from `/home/pruefstand/demo.env`)
maps `https://demo.<domain>` to `http://rag-demo:8000`, so the VM opens no inbound port. The image is
deployed only as a **demo-ready** digest by the private nightly job `demo-deploy` (D244): it pulls the
**public GHCR image by digest**, anonymously; no artefact is downloaded and no token is needed (N5.3,
UI12-03). It makes **one** anonymous API call per night, `GET …/releases/latest` (P5.3; the 60/h
anonymous limit is never reached; 403/429 → keep the deployed digest), and downloads the release assets
`demo-ready.json` and `image-digests.json` through their `browser_download_url`. Only a release whose
`demo-ready.yml` leak probes passed has `demo-ready.json` (uploaded by job `release-demo-ready`, T8.5;
`deploy.yml` is dashboard-only, UI13-06); its digest must equal the rag-demo digest of
`image-digests.json` and is verified with `cosign` before use. Rollback = the `demo-nightly.yml`
dispatch mode `pin` (writes `pin.json` with an expiry); kill switch = dispatch mode `disable`, which
touches the file flag `/run/demo/disabled` inside the container (503 at once, no restart; UI13-11). Rate limits, daily counters and the token budget are **in-process** state of the one
rag-demo process. A container restart resets them. `rag.public.yaml` sets `reranker: off` (UI11-16).
**Client key (one source, UI12-10):** the `X-Forwarded-For` hop selected by `TRUSTED_PROXY_HOPS`; `1`
on the public demo (cloudflared appends the visitor address as the last hop), `0` on the e2e instance
(key = the TCP peer address rag-demo sees: for host connections through the published port that is the
Docker bridge gateway, stable for the run, not `127.0.0.1`; UI13-04). `CF-Connecting-IP` is not read. `DEMO_ALLOWED_ORIGIN` = the dashboard
origin (`https://dheena18.github.io`; shared by every Pages site of the owner, an accepted residual
recorded in `security.md`, UI12-19). The test-only reset endpoint `POST /v1/_test/reset` (N5.4) exists
only when `DEMO_TEST_RESET=1`, which the `demo` profile never sets, and is only ever called from inside
the e2e container (P5.4, §14.2). Server timeout `DEMO_TIMEOUT_S` defaults to **75**, which is below the
client's `NEXT_PUBLIC_DEMO_TIMEOUT_S` (default 90), so a slow generation shows the server `timeout` path
(UI11-17). The demo costs nothing beyond the VM and a domain the owner already has.

```text
Try the demo RAG app
Pick a tenant. Each tenant only sees its own documents plus shared public laws.
Tenant  (•) Kanzlei Müller — law firm, labour law
        ( ) Versicherung Nord — insurer, insurance contract law
        ( ) Stadtwerke Süd — utility, energy law, GDPR, NIS2
Question (German)                                                      123 / 500
┌──────────────────────────────────────────────────────────────────────────────┐
│ Welche Kündigungsfrist gilt nach zwei Jahren?            (textarea lang="de") │
└──────────────────────────────────────────────────────────────────────────────┘
Examples: [Welche Kündigungsfrist gilt nach zwei Jahren?] [ … ] [ … ]
[ Ask ]   Answers come from a small CPU model and can take up to a minute.
Limits per visitor and a shared daily budget apply.
── Answer ─────────────────────────────── 12.4 s · model <model>
(lang=de) Nach § 622 Abs. 2 BGB …
Citations: [§ 622 Abs. 2 BGB]
Retrieved chunks
 #1 <chunk text, lang=de, collapsible after 6 lines>  doc_id · score 0.82 · [kanzlei_mueller]
 #4 <chunk text …>  doc_id · score 0.41 · [shared_public] · not sent to the model
──────────────────────────────────────────────────────────────────────
<LicenceNotice full>
```

- Tenant labels and descriptions come from `src/content/try.json`:
  `{tenants: [{id, label: {de, en}, description: {de, en}}], examples: [{tenant, question}], refusal_example: {tenant, question}}`
  (T8.4): real slice-corpus questions with a verified answer, ≥ 1 per tenant, plus one verified refusal
  question (used by `T-REFUSED` tests). Examples and the textarea are German data (`lang="de"`) on
  `/en` as well (UI9-21).
- The limits line is `try.limits` and has no numbers (the limits are server env, UI9-21).
- Chunk cards show `try.not_in_prompt` when the response chunk has `used_in_prompt == false`; nothing
  when it is `true` or absent (X3.14).

**Error contract (W5.5, interfaces §16, D138):** every 4xx/5xx in public mode returns
`application/json` `{"code": <code>, "message": <English text for API users>, "retry_after_s": int | null}`.
The UI never reads the `Retry-After` header and never displays `message` (§10.3); it maps `code` to
§10.4 strings. Unknown code or non-JSON body → `T-SERVER-ERROR` (5xx) or `T-REJECTED` (4xx).
Status codes and triggers below are the UI's expectations; interfaces §16 fixes the code names.

| `code` | HTTP | When | `retry_after_s` |
| --- | --- | --- | --- |
| `rate_limited` | 429 | > 10 req/min for the client key | seconds until the bucket refills |
| `daily_limit` | 429 | per-key 100/day or global 2,000/day | seconds to 00:00 UTC |
| `busy` | 429 | `DEMO_MAX_CONCURRENCY` generations already running (no queue) | 5 |
| `budget_exhausted` | 503 | daily token or request budget used up | seconds to 00:00 UTC |
| `demo_disabled` | 503 | kill switch (env or file flag) | null |
| `invalid_request` | 422 | unknown tenant, empty or > 500-char question, bad JSON | null |
| `body_too_large` | 413 | body > 8 KB | null |
| `timeout` | 504 | server-side generation timeout (`DEMO_TIMEOUT_S`, default 75) | null |

State machine (pure `useReducer`, unit-tested; one `aria-live="polite"` region announces transitions;
error panels `role="alert"`). Validation runs on every input event after the first input, and on
submit; never on blur.

| State id | Trigger | UI |
| --- | --- | --- |
| `T-DISABLED` | `NEXT_PUBLIC_DEMO_API_URL` unset at build | no nav link; direct visit → `try.unavailable` |
| `T-IDLE` | load (question empty), or a valid question | form enabled; Ask disabled while the question is empty; no error shown at load |
| `T-INVALID` | after the first input or a submit: empty, or > 500 chars (counter fail colour at 500, input stops at 500) | inline error (`try.invalid.empty` / `try.invalid.too_long`), `aria-describedby`, Ask disabled |
| `T-LOADING` | submit | Ask → `try.asking` + spinner, disabled (double-submit guard); elapsed-seconds counter; Cancel (AbortController); inputs read-only |
| `T-SLOW` | loading > 10 s | adds `try.slow` |
| `T-TIMEOUT` | loading > `NEXT_PUBLIC_DEMO_TIMEOUT_S` (default 90) → client abort, or server `timeout` | `try.error.timeout` + Retry |
| `T-CANCELLED` | Cancel pressed | back to idle; `try.cancelled` announced |
| `T-SUCCESS` | 200 | answer card; focus → answer heading |
| `T-REFUSED` | 200 with `refused == true` | answer card + info badge `try.refused` |
| `T-RATE-LIMITED` | `rate_limited` | `try.error.rate_limited` + `RetryCountdown` from `retry_after_s`; Ask disabled until 0 |
| `T-BUSY` | `busy` | `try.error.busy` + countdown |
| `T-DAILY-LIMIT` | `daily_limit` | `try.error.daily_limit`; Ask disabled for the page session |
| `T-BUDGET` | `budget_exhausted` | `try.error.budget`; Ask disabled for the page session |
| `T-DEMO-OFF` | `demo_disabled` | `try.error.disabled` |
| `T-REJECTED` | `invalid_request`, `body_too_large`, unknown 4xx | `try.error.rejected` |
| `T-NETWORK` | fetch throws (offline, CORS, DNS) | `try.error.network` + Retry |
| `T-SERVER-ERROR` | other 5xx, unknown code, non-JSON body | `try.error.server` + Retry |

CORS keeps `Access-Control-Expose-Headers: Retry-After` for other clients; the UI does not depend on
it. The page's CSP `connect-src` allows exactly the demo API origin (§7.4).

### 4.7 Licences page and attribution footer (W5.4, UI-07, UI9-23)

- `scripts/dashboard/gen_licences.mjs` turns `DATA_LICENSES.md` into `src/content/licences.json`
  (`sources: [{id, name, shown_here, licence, licence_url, attribution, url}]`, `odbl_offer`,
  `footer_line: {de, en}`) **and** writes the same JSON to
  `packages/pruefstand/src/pruefstand/report/templates/_licences.json` (package data read by
  `render_html`). CI drift check on both files, like `gen:types`. T6.4 ships a first copy of
  `_licences.json` by hand; T8.1's generator replaces it.
- `/licences/`: `DataTable` source · shown here · licence · attribution · link; ODbL notice and the
  offer of the derivative database. MEMERAG is not listed (never redistributed).
- **Footer on every page** (`AppFooter`, incl. root redirect, 404, error boundary, Try it):
  `footer_line` in the page locale, link to `/<locale>/licences/` (root redirect and 404: `/de/licences/`),
  pruefstand version, export time and `footer.no_certificate`. `report.html` carries
  `footer_line.en` from `_licences.json` (§13).

### 4.8 Not found and error pages

- `out/404.html` (from `src/app/not-found.tsx`, de) and `[locale]/not-found.tsx` render the same
  `NotFoundView`: `notfound.title` + links to the runs list, plus `notfound.docs`
  ("Documentation" / "Dokumentation") to `${basePath}/docs/`, shown **only when `basePath` is set**
  (in a local build `/docs/` would itself be a 404; UI12-09). The docs link is a plain `<a href>`. GitHub
  Pages serves the site-root `404.html` with status 404 for every unknown path. This is the site's error
  state (`X-404`, X1.2).
- `[locale]/error.tsx`: `ErrorPanel` with Reload and the error class (`UnsupportedSchemaError`,
  `NotFoundError`, `ValidationError`); never a stack trace. Pre-rendered pages cannot reach it (data is
  validated at build), so it is tested in Vitest only (`X-ERROR`).

### 4.9 HTML report link

"Open HTML report ↗" (`${basePath}/data/runs/<id>/report.html`, same tab) and "Download" (`download`
attribute) appear exactly when the run has `gate.json` (`RunIndexEntry.status != null`) **and** is a
case-published run (`cases/<id>/0.json` exists at build time), because the export writes `report.html`
in exactly that case (§2.3, N5.1). Both are plain `<a href>` elements, never `next/link`: the target is
outside the Next app, and a client navigation would request an RSC payload first (UI12-09).
`validate_data.mjs` (§2.4 rules 3, 9) and T8.5's verify step enforce the pairing, so there is never a
dead link.

---

## 5. Component inventory

| Component | Used on | Props (source) | States / variants | A11y |
| --- | --- | --- | --- | --- |
| `AppHeader` | all | locale, theme, `demoEnabled` | desktop / mobile sheet | skip link, `nav aria-label` |
| `AppFooter` | all | `licences.json`, version, export time | – | `contentinfo` |
| `LocaleSwitch` | header | path + query | – | two links, `hreflang`, `lang` on each label, `aria-current` |
| `ThemeToggle` | header | system/light/dark | 3-state cycle | `button` `aria-label` "Theme: system" |
| `RunSubNav` | run pages | run id, failing count (shard 0), gated, `no_baseline`, cases published | Diff/Slices disabled: "(not gated)" without `gate.json`, "(nothing compared)" with `no_baseline`; Cases disabled "(cases not published)" for `S-CASES-PRUNED` | `aria-current="page"`; disabled = `aria-disabled` span |
| `StatusBadge` | everywhere | `GateStatus` \| `"NOT_GATED"` \| `"NO_BASELINE"` | sm / md / lg | icon `aria-hidden`, text visible |
| `TierBadge` | runs list, summary | `stack` | 1 / 2 | text "Tier 1" / "Tier 2" |
| `Banner` | run pages, try | severity, key, params | max 3 + disclosure | `role="status"` (error `alert`) |
| `RunMetaBlock` | summary | run.json cand + base | baseline missing | `<dl>` |
| `HardFailList` | summary | `hard_fails` | tier 2 list / tier 1 row + findings | `h2`; evidence `lang="de"` |
| `MetricTable` | summary, diff table, HTML report | block G or R rows (§11.1) | gated (7 columns) / reported (tier 1) | `<caption>`, `scope`, `tabular-nums` |
| `AbsoluteCheckTable` | summary | block A or C rows (+ hard-fail row in tier 1) | tier 2 / tier 1 checks | as `MetricTable` |
| `InformationalTable` | summary | block I rows | reason column | caption "informational, does not block" |
| `JudgedInfoTable` | summary | block J rows, `judge_mode`, `judged_cases` | judged / skipped | caption "informational, does not block" |
| `Tier1Notice` | summary, diff, slices | `stack`, `splits`, `n_cases` | – | `role="note"` |
| `CiBar` | diff | `BootstrapResult`, `max_drop`, domain | null → "n/a"; insufficient greyed; no threshold | `role="img"` + label "Δ −0.09, 95 % CI −0.12 to −0.06, threshold −0.05, FAIL" |
| `CiChart` | diff | rows | ≤ 50 rows per chart, else paginated | `figure` + `figcaption`; table toggle |
| `SliceChart` | slices | `DashboardSliceRow[]` | grouped by the §11.1 rule; ≤ 12 bars | `role="img"`, label, table fallback |
| `DataTable` | lists | rows, columns, sort, page | loading, empty, filtered-empty | `aria-sort`; focusable scroll region ≥ 640 px; cards < 640 px |
| `Pagination` | lists | page, total | – | `nav aria-label`, `aria-current` |
| `FilterBar` | lists | URL query | – | labelled controls; count `aria-live` |
| `CaseListItem` | cases | `DashboardCase` | failing / passing / selected | link; selected `aria-current="true"` |
| `CaseDetail` | case panel, case page | `DashboardCase` cand + base, case hard fails | loading / baseline missing / not found / shard error | `h2` focus target |
| `AnswerPair` | case detail | two answers, `case.lang` | one missing, refused, error | two `section`s; `lang={case.lang}` |
| `CitationList` | case detail, try | `citations` | empty | list; `lang="de"` |
| `ChunkCard` | case detail, try | chunk id, chunk tenant (R3 / try response), case tenant, text (try only), `used_in_prompt` (try only) | own / shared_public / **leak** / tenant unknown | leak = fail colour + "⚠ LEAK" text + label |
| `TenantBadge` | chunk cards, filters | tenant id | own, shared, foreign | text always |
| `EmptyState` | lists, pages | i18n key, action | – | heading + text + optional button |
| `ErrorPanel` | error boundary, shards, try | error kind | retry / reload | `role="alert"` |
| `NotFoundView` | 404, `[locale]/not-found` | locale, `basePath` | docs link only when `basePath` is set (`notfound.docs`, §4.8) | one `h1`; the docs link is a plain `<a href>` (never `next/link`) |
| `Skeleton` | lists, shards | shape | – | `aria-hidden`; container `aria-busy` |
| `ReportLink` | summary | `RunIndexEntry.status != null` and case-published run (§4.9) | absent → nothing | link text names the HTML report; open and Download are plain `<a href>` with `basePath` (never `next/link`) |
| `TryItForm` | try | tenants, examples | §4.6 states | `fieldset/legend`; counter `aria-live` only ≥ 450 chars |
| `AnswerCard` | try | `/v1/query` response | success / refused | heading focus target |
| `RetryCountdown` | try | `retry_after_s` | – | announces start and end only |
| `LicenceNotice` | try, footer, /licences | `licences.json` | compact / full | – |

Every component: one file ≤ 300 lines, a Vitest test per variant, rendered in the matrix (§14).
Positions and sizes use SVG attributes or CSS classes, never a `style` attribute in server-rendered
markup (§7.4). Icons: inline Lucide SVG (ISC) — `check-circle` PASS, `alert-triangle` WARN, `x-circle`
FAIL, `circle-dashed` INSUFFICIENT_DATA, `alert-octagon` UNSUPPORTED_CONFIG, `circle` NOT_GATED,
`circle-slash` NO_BASELINE, `shield-alert` LEAK, `info` informational and judge notices.

---

## 6. Global state catalogue

State ids are used by the fixture matrix (§14.1) and the test matrix (§14.2).

| Id | Where | Behaviour |
| --- | --- | --- |
| `S-PASS` / `S-WARN` / `S-FAIL` | summary, diff, slices, cases | status block + §4.2.1 sections |
| `S-HARD-FAIL` | summary, cases (leak chunk) | hard-fail panel first; counted as blocking (tier 1 and tier 2) |
| `S-INSUFFICIENT` | summary, diff, slices | greyed rows + "insufficient data (n clusters < 30)" |
| `S-TIER1` | summary, diff, slices | tier-1 body (§4.2.2), `Tier1Notice`; paired metrics reported (`tier1_deterministic_only`) |
| `S-PARTIAL` | summary, cases | warn banner (reason `stop_reason.aborted_infra` when `infra_error` is set, §4.2); gate sections replaced by "not gated"; `run.json.counts` shown; Diff/Slices disabled |
| `S-NOT-GATED` | summary, cases | info banner; Diff/Slices disabled; cases without failing markers |
| `S-NO-BASELINE` | summary, runs list, PR comment, report, sub-nav | alert banner `banner.no_baseline`; `⊘ NO BASELINE` badge (⚪ in Markdown); no metric tables (nothing was compared); hard fails still shown; never PASS styling; Diff/Slices disabled "(nothing compared)" and not generated (UI11-20) |
| `S-JUDGE-SKIPPED` | summary, runs list flag | info banner; judged section shows the skipped text, no numbers |
| `S-JUDGE-FALLBACK` / `S-JUDGE-DEGRADED` / `S-JUDGE-DRIFT` | summary, runs list flag | warn banner; judged rows in block I with the reason |
| `S-UNSUPPORTED` | summary | warn banner; counted as WARN |
| `S-BASELINE-MISSING` | summary, cases | info banner (only when `baseline_run_id` is not null); baseline columns "–"; "Baseline not exported" panel |
| `L-POPULATED` / `L-EMPTY` / `L-FILTERED-EMPTY` | runs list | §4.1 |
| `S-CASES-PRUNED` | summary, sub-nav | run outside the newest 20 (§2.3, N5.1): Cases "(cases not published)", no report link, top failing ids without links; its cases paths are the 404 page |
| `E-PLACEHOLDER` | `runs/_empty/**` (empty set; populated set when a page has no real params), `runs/<id>/cases/_empty/` (published run without failing cases) | `EmptyState` (§2.1, Y7.2, UI12-08); `noindex`; never linked |
| `C-LOADING` / `C-SHARD-ERROR` / `C-NOT-FOUND` | cases | §4.5 |
| `T-*` | try | §4.6 |
| `X-404` | any unknown path | §4.8; the site's error state (X1.2) |
| `X-ERROR` | error boundary | §4.8; Vitest only |
| `B-INVALID-DATA` | build | §2.4: the build fails and names the file; no page is produced. Tested in `validate-data.test.ts` (T8.1) |

Loading: static pages are pre-rendered; only shard loads and Try it have loading states; skeletons
are sized like the final content (CLS < 0.1).

Query-driven pages (UI11-09: runs list, cases list, diff `?sort`/`?slice`, slices): the static HTML is
the **default view** (no filters, page 1, default sort), rendered from build-time data as the
`<Suspense>` fallback around the `useSearchParams` reader. After hydration the client applies the
query; with no query the view does not change. The default view is never a skeleton, so the no-JS
content (§8) and the "only shard loads and Try it have loading states" rule both hold. After hydration
`<main>` gets `data-hydrated="true"`; Playwright waits for `[data-hydrated]` before it asserts a
query-driven state.

---

## 7. Design tokens (`apps/dashboard/src/styles/tokens.css`)

Themes: `:root` = light, `[data-theme="dark"]` = dark, `[data-theme="system"]` follows
`prefers-color-scheme`. Default = system. Choice in `localStorage["pruefstand.theme"]` (try/catch),
applied before first paint by `public/theme-init.js`, loaded with a blocking
`<script src="<basePath>/theme-init.js">` in `<head>` of every document (never an inline script, X5.2). Tailwind reads the variables. `report.html` inlines
the same values: `scripts/dashboard/tokens_to_report.mjs` writes
`packages/pruefstand/src/pruefstand/report/templates/_tokens.css` from `tokens.css` (CI drift check,
added by T8.1; T6.4 ships a first copy by hand-copying the table below, and T8.1 replaces it with the
generated file).

### 7.1 Colour (light / dark)

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `--bg` | `#ffffff` | `#0b1120` | page |
| `--surface` | `#f8fafc` | `#111827` | cards, table header |
| `--surface-2` | `#f1f5f9` | `#1f2937` | hover, skeleton |
| `--border` | `#cbd5e1` | `#334155` | decorative dividers only |
| `--border-strong` | `#64748b` | `#94a3b8` | inputs, focusable outlines (≥ 3:1) |
| `--text` | `#0f172a` | `#e5e7eb` | body |
| `--text-muted` | `#475569` | `#9ca3af` | secondary text (≥ 4.5:1 on `--bg`, `--surface`, `--surface-2`) |
| `--accent` | `#1d4ed8` | `#60a5fa` | links, primary button |
| `--accent-contrast` | `#ffffff` | `#0b1120` | text on accent |
| `--focus` | `#1d4ed8` | `#93c5fd` | 2 px outline + 2 px offset |
| `--pass-fg` / `--pass-bg` | `#15803d` / `#f0fdf4` | `#4ade80` / `#052e16` | PASS |
| `--warn-fg` / `--warn-bg` | `#b45309` / `#fffbeb` | `#fbbf24` / `#422006` | WARN, UNSUPPORTED_CONFIG, judge warnings |
| `--fail-fg` / `--fail-bg` | `#b91c1c` / `#fef2f2` | `#f87171` / `#450a0a` | FAIL, LEAK, no-baseline banner |
| `--insufficient-fg` / `-bg` | `#475569` / `#f1f5f9` | `#9ca3af` / `#1f2937` | INSUFFICIENT_DATA, NOT_GATED, NO_BASELINE badge |
| `--info-fg` / `--info-bg` | `#1d4ed8` / `#eff6ff` | `#93c5fd` / `#172554` | informational, tier-1 notice, info banners |
| `--chart-baseline` | `#64748b` | `#94a3b8` | baseline bars (hatched) |
| `--chart-candidate` | `#1d4ed8` | `#60a5fa` | candidate bars (solid) |
| `--chart-threshold` | `#b91c1c` dashed | `#f87171` dashed | −δ line |
| `--chart-zero` | `#0f172a` | `#e5e7eb` | 0 line |

**Tested pairs** (`test/styles/contrast.test.ts` parses `tokens.css`; both themes; values may change
to pass, the test is the authority; UI9-25):

| Foreground | Background | Minimum |
| --- | --- | --- |
| `--text`, `--text-muted`, `--accent` | `--bg`, `--surface`, `--surface-2` | 4.5:1 |
| `--accent-contrast` | `--accent` | 4.5:1 |
| each status fg (`--pass-fg`, `--warn-fg`, `--fail-fg`, `--insufficient-fg`, `--info-fg`) | its own bg and `--bg` | 4.5:1 |
| `--border-strong`, `--focus` | `--bg`, `--surface` | 3:1 |
| `--chart-baseline`, `--chart-candidate`, `--chart-threshold`, `--chart-zero` | `--bg` | 3:1 |

Charts also encode by shape: candidate solid, baseline hatched, insufficient dotted.

### 7.2 Typography

- Inter (variable, OFL-1.1) and JetBrains Mono (OFL-1.1) via `next/font/local` (no network).
  Fallback `system-ui`, `ui-monospace`. `report.html` uses the system stacks only.
- Scale (rem): `--text-xs` 0.75 (labels only), `--text-sm` 0.875 (tables), `--text-base` 1,
  `--text-lg` 1.125, `--text-xl` 1.25, `--text-2xl` 1.5, `--text-3xl` 1.875 (status). Line height 1.5
  body, 1.25 headings.
- Numbers `tabular-nums`, right-aligned. Ids, SHAs, chunk ids, metric codes: mono `--text-sm`.
- Survives 200 % zoom and WCAG 1.4.12 text spacing without clipping.

### 7.3 Spacing, radius, elevation, motion, targets

- 4 px grid: `--space-1` 4, `-2` 8, `-3` 12, `-4` 16, `-6` 24, `-8` 32, `-12` 48 px.
- Radius `--radius-sm` 4 px, `--radius-md` 8 px. One shadow `--shadow-1` (none in dark; border instead).
- Motion ≤ 150 ms ease-out; off under `prefers-reduced-motion` and in test mode.
- Hit targets ≥ 24 × 24 CSS px (WCAG 2.5.8); 44 × 44 for primary actions < 640 px.

### 7.4 Content Security Policy (X5.2, UI9-03; GitHub Pages, Y7.1)

GitHub Pages cannot set response headers, so **every policy is a `<meta http-equiv="Content-Security-Policy">`
with hashes**. There are no header files (`headers.json`, `vercel.json`, `_headers`). Directives that a
meta policy ignores (`frame-ancestors`, `report-uri`, `sandbox`) are not written. Clickjacking
protection (`frame-ancestors`) and `X-Content-Type-Options` are therefore not under our control. This is
an accepted risk: the site is read-only static content with no state-changing action
(`docs/engineering/security.md`, T8.5). Referrer policy is a meta tag:
`<meta name="referrer" content="strict-origin-when-cross-origin">`.

Rules:
- **No inline script of our own.** Theme init and every other script we write are files. The root
  redirect uses meta refresh only. `'unsafe-inline'` never appears in `script-src`. The only inline
  scripts in site pages are the RSC/hydration scripts that Next.js emits. They are allowed by their
  `sha256` hash, per page.
- **Styles come from build-time CSS files** (`style-src 'self'`). Server-rendered HTML has no `<style>`
  element and no `style` attribute. Charts render client-only (§8), and React applies their styles
  through the CSSOM, which CSP allows.
- **`report.html` is a separate document** with its own meta policy (inline styles allowed), written by
  `render_html` itself (T6.4). The dashboard build never edits it.

Mechanics (created by T8.1, so the local Playwright server and GitHub Pages serve identical bytes):
1. `scripts/dashboard/csp.mjs` (post-build) hashes each inline `<script>` of each `out/**/*.html`
   (except `data/**`) and inserts, as the first child of `<head>` (before any script),
   `<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'sha256-…'…; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'[ <demo-api-origin>]; object-src 'none'; base-uri 'self'; form-action 'self'">`
   and the referrer meta. `<demo-api-origin>` = origin of `NEXT_PUBLIC_DEMO_API_URL`, only when it is
   set at build. `'self'` covers `basePath` (same origin).
2. **Report policy (UI11-10).** `render_html` writes, as the first child of the report's `<head>`,
   `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-<hash>'; img-src data:; base-uri 'none'; form-action 'none'">`,
   where `<hash>` is the sha256 of the exact `_sort.js` bytes **it** inlines. Every report therefore
   carries the hash of its own script, whatever pruefstand version exported it, and old reports in
   `pruefstand-dashboard-data` never break after a `_sort.js` change.
3. `scripts/dashboard/check_csp.mjs` fails the build on: any `style=` attribute, `<style>` element or
   unhashed inline `<script>` in `out/**/*.html` outside `data/`; any such page without exactly one CSP
   meta; any `out/data/runs/*/report.html` without exactly one CSP meta whose `script-src` hash equals
   the sha256 of its inline script. It also fails if `out/` contains `headers.json`, `_headers` or
   `vercel.json`.
4. Local serving (`serve`, Playwright `webServer`) uses `build_set.sh`'s `serve.json` with
   `{"cleanUrls": false, "trailingSlash": true}` and **no headers**, like GitHub Pages.
5. Playwright (`matrix.spec.ts`, `smoke.deployed.spec.ts`) fails on any `securitypolicyviolation`
   event or CSP console error, and asserts that each document has **exactly one CSP `<meta>`** and no
   `Content-Security-Policy` response header.

---

## 8. Charts (Recharts)

| View | Chart | Why | Not |
| --- | --- | --- | --- |
| Diff | horizontal dot-and-whisker per gated pair, shared x, 0 line, −δ line per row | the rule is "CI vs −δ" | no bar-from-zero |
| Slices | grouped horizontal bars baseline vs candidate per value + Δ label | compare levels across values | no radar/pie |
| Runs list, tier-1 pages | none | tables are faster; n = 20 has no CI to draw | – |

Axis labels in metric units, 2 decimals, Unicode minus; tooltips only duplicate visible text; no
animation. Every chart is in a `<figure>` + `figcaption` + "Show as table". The table is
server-rendered and always in the DOM (visually hidden while the chart shows), so content works without
JS (WCAG 1.1.1). Charts load client-only (JS < 250 kB per page; §7.4). Next 15 rejects
`next/dynamic(…, {ssr: false})` inside Server Components (UI11-22), so each chart has a `'use client'`
wrapper file `src/components/charts/<Name>.client.tsx` that calls `next/dynamic` with `ssr: false`.
Pages and server components import only the wrapper.

---

## 9. Accessibility (WCAG 2.2 AA)

| Criterion | Rule here | Checked by |
| --- | --- | --- |
| 1.1.1 | charts `role="img"` + label + table alternative; icons `aria-hidden` next to text | axe + `a11y.spec.ts` |
| 1.3.1 | tables `<caption>` + `scope`; labelled forms; one `h1`, ordered headings | axe |
| 1.4.1 | status icon + text; leak text; chart patterns | `StatusBadge.test.tsx`, visual |
| 1.4.3 / 1.4.11 | §7.1 tested pairs, both themes | `contrast.test.ts`, axe light + dark |
| 1.4.10 | no page-level horizontal scroll at 360 px; 1280 px at 400 % zoom | `reflow.spec.ts` |
| 1.4.12 | no clipping with WCAG text-spacing CSS | `reflow.spec.ts` |
| 2.1.1 / 2.1.2 | all controls keyboard-operable; only trap = open mobile sheet (Esc exits) | `keyboard.spec.ts` |
| 2.4.1 | skip link | `keyboard.spec.ts` |
| 2.4.3 / 2.4.7 | DOM order = visual order; focus outline never removed | `keyboard.spec.ts` + visual |
| 2.4.11 | sticky header + `scroll-padding-top: 72px` | `keyboard.spec.ts` (focused rect below header) |
| 2.5.8 | targets ≥ 24 × 24 | `a11y.spec.ts` measures `button, a, [role=button], input, select` |
| 3.1.1 / 3.1.2 | `<html lang>` = route locale (static; root redirect and 404 `de`); question/answer `lang={case.lang}`; evidence, citations, chunk text `lang="de"` | `content.spec.ts` (incl. one `en` case) |
| 3.2.2 | filters never move focus or navigate away | `filters.spec.ts` |
| 3.3.1 / 3.3.3 | try inline errors, `aria-describedby` | `try.spec.ts` |
| 4.1.3 | try transitions, filter counts, shard loading via `aria-live="polite"` | `try.spec.ts`, `filters.spec.ts` |

Manual check per milestone (M6, M7): NVDA + Firefox and VoiceOver + Safari through the navigation and
Try-it flows in both locales; recorded in `apps/dashboard/README.md`.

---

## 10. Language and copy

### 10.1 i18n mechanics (W5.4)

- Locales `de` (default) and `en`; route prefix `/de/…`, `/en/…` via `src/app/[locale]/`; the layout
  renders `<html lang={locale}>` statically (no lang script). Root redirect and 404 are `de`.
- Chrome strings in `src/i18n/{de,en}.json`, flat keys (`runs.title`, `try.error.rate_limited`).
  `test/i18n.test.ts` asserts identical key sets and identical ICU placeholders, except the four
  `de`-only data-label prefixes below.
- Data labels (UI-26, UI9-09, UI9-20): `en` comes from `data/labels.json` (`LabelsDocument`, generated
  by `labels_document()` in T1.9, copied by `export-dashboard`); `de` comes from `de.json` keys
  `metric.<code>`, `cause.<code>`, `rule.<code>`, `info_reason.<code>` (these prefixes exist in `de.json`
  only).
- Hard-fail rule names (UI12-15, D273): `LabelsDocument.hard_fail_rules: dict[str, str]` maps each rule
  code to its en label (interfaces §10.1), like `metrics` and `informational_reasons`, so `/en` never
  shows a raw rule code. `stop_reason.<code>` keys are chrome and exist in both files.
- A test asserts that every code in the fixture `labels.json` (`metrics`, `causes`,
  `informational_reasons`, `hard_fail_rules` keys) has a `de` key, that every `hard_fail_rules` value is
  a non-empty en label, and that `de.json` has no stale code. Unknown code at runtime → the raw code in
  mono.
- Root `/` → `/de/` (§2.1). No `navigator.language` sniffing, no stored locale.
- `LocaleSwitch` keeps path and query; `<link rel="alternate" hreflang>` for both locales on every page.
- Dates (UI9-13), all in `Europe/Berlin`:
  - `de`: `Intl.DateTimeFormat("de-DE", {dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Berlin", timeZoneName: "short"})`
    → `31.10.2026, 14:02 MEZ` (summer: `MESZ`);
  - `en`: assembled with `formatToParts` as `yyyy-MM-dd HH:mm` + the `en-GB` short zone name →
    `2026-10-31 14:02 CET` (summer: `CEST`);
  - `format.test.ts` covers a winter date and a summer date in both locales.
- Report and PR comment dates are UTC, ISO-like: `2026-10-31 13:02 UTC`.

### 10.2 Number formats (identical in dashboard, HTML report, PR comment)

| Kind | Format | Example |
| --- | --- | --- |
| metric value | 2 decimals | `0.86` (de: `0,86`) |
| Δ | sign always, Unicode minus, 2 decimals | `−0.07`, `+0.01` |
| Δ with CI | `Δ (low, high)` | `−0.07 (−0.10, −0.04)` |
| δ, max, MDE | 2 decimals, no sign | `0.05` |
| duration | `Xm Ys` | `18m 12s` |
| cost | `0.18 USD`, zero → `0 USD` | |
| tokens | `cost.prompt_tokens + cost.completion_tokens`: `4.1 M`, `812 k`, `< 1 k` (one sum on every surface) | |
| GPU-s | `~2,100 GPU-s` (de `~2.100 GPU-s`); only when `stack == "a40"` | |
| ref label | §2.2 | `pr-42@d4e5f6a` |
| missing | en dash `–` | |

PR comment and HTML report are English-only (`.` decimal); the dashboard uses the locale's separator.

### 10.3 Copy rules

- Plain words, short sentences: status, reason, next step.
- "does not block" for informational data; never "warning" for informational.
- Never "compliant"/"konform"; "supports documentation" / "unterstützt die Dokumentation".
- Never show raw exceptions, HTTP bodies, API `message` fields or stack traces.
- German copy: neutral imperatives ("Später erneut versuchen").
- Status words are product terms, not translated: PASS, WARN, FAIL, INSUFFICIENT DATA,
  UNSUPPORTED CONFIG, NOT GATED, NO BASELINE; explanations are translated.

### 10.4 Key strings (en / de)

#### 10.4.1 Banners, notices, cases, try

| Key | en | de |
| --- | --- | --- |
| `banner.incomplete` | Incomplete run — not gated (stop reason: {reason}). | Unvollständiger Lauf — nicht bewertet (Abbruchgrund: {reason}). |
| `banner.not_gated` | Not gated — this run has no gate report. | Nicht bewertet — für diesen Lauf gibt es keinen Gate-Bericht. |
| `banner.no_baseline` | No baseline for this evaluation fingerprint — nothing was compared. Run baseline-promote. | Keine Baseline für diesen Evaluations-Fingerabdruck — nichts verglichen. baseline-promote ausführen. |
| `banner.judge_skipped` | Judge skipped (quota used up). Judged metrics are not shown; the deterministic gate still decided. | Judge übersprungen (Kontingent aufgebraucht). Bewertete Metriken fehlen; das deterministische Gate hat entschieden. |
| `banner.judge_fallback` | Some judgments came from the fallback judge; judged metrics are informational. | Einige Bewertungen stammen vom Ersatz-Judge; bewertete Metriken sind nur informativ. |
| `banner.judge_degraded` | The judge failed on more than 5 % of cases; judged metrics are informational. | Der Judge ist bei mehr als 5 % der Fälle ausgefallen; bewertete Metriken sind nur informativ. |
| `banner.judge_drift` | Judge drift detected (5 or more of 50 anchor verdicts changed); judged metrics are informational until the flag clears. | Judge-Drift erkannt (5 oder mehr von 50 Ankerurteilen geändert); bewertete Metriken sind informativ, bis die Markierung aufgehoben ist. |
| `banner.unsupported` | Unsupported configuration — counted as WARN. | Nicht unterstützte Konfiguration — zählt als WARN. |
| `banner.baseline_missing` | Baseline run {id} is not in this export; baseline details unavailable. | Baseline-Lauf {id} ist nicht im Export; keine Baseline-Details. |
| `banner.more` | {n} more notices | {n} weitere Hinweise |
| `tier1.notice` | Tier 1 decides on hard fails and the error rate only ({split}, {n} cases). Language, citation, refusal and injection results are reported. Paired statistics need ≥ 30 clusters and run in tier 2. | Stufe 1 entscheidet nur über harte Fehler und die Fehlerquote ({split}, {n} Fälle). Sprache, Zitate, Ablehnung und Injection werden berichtet. Gepaarte Statistik braucht ≥ 30 Cluster und läuft in Stufe 2. |
| `tier1.reported` | Reported — does not decide at n = {n} | Berichtet — entscheidet nicht bei n = {n} |
| `tier1.checks` | Checks (decide) | Prüfungen (entscheiden) |
| `tier1.hard_fail_row` | Hard fails (canary, tenant, system prompt) | Harte Fehler (Canary, Mandant, Systemprompt) |
| `slices.informational` | Informational, does not block | Informativ, blockiert nicht |
| `slices.gated` | Gated slices | Bewertete Slices |
| `slices.notable` | notable | auffällig |
| `slices.show_all` | Show all {n} in table | Alle {n} als Tabelle zeigen |
| `case.baseline_missing` | Baseline not exported | Baseline nicht exportiert |
| `case.not_found` | Case {id} not found in this run. | Fall {id} ist in diesem Lauf nicht vorhanden. |
| `case.question` | Question | Frage |
| `case.baseline_answer` | Baseline answer | Baseline-Antwort |
| `case.candidate_answer` | Candidate answer | Kandidaten-Antwort |
| `case.no_answer` | no answer | keine Antwort |
| `case.refused` | Refused | Abgelehnt |
| `case.expected_refusal` | expected: refusal | erwartet: Ablehnung |
| `case.error` | Error: {class} | Fehler: {class} |
| `case.citations` | Citations | Zitate |
| `case.no_citations` | no citations | keine Zitate |
| `case.metrics` | Metrics | Metriken |
| `case.na` | n/a (not applicable) | n. a. (nicht anwendbar) |
| `case.metric_error` | error | Fehler |
| `case.chunks` | Retrieved chunks (rank order) | Abgerufene Abschnitte (nach Rang) |
| `case.leak_in_case` | ⚠ LEAK in this case | ⚠ LECK in diesem Fall |
| `chunk.leak` | Leak: chunk from tenant {tenant} | Leck: Abschnitt von Mandant {tenant} |
| `chunk.text_withheld` | Chunk text is not published (sanitised data). | Abschnittstext wird nicht veröffentlicht (bereinigte Daten). |
| `cases.title` | Cases ({total}) | Fälle ({total}) |
| `cases.failing` | {n} failing | {n} fehlschlagend |
| `cases.partial` | (partial) | (unvollständig) |
| `cases.loading` | Loading cases: {loaded} of {total} parts | Fälle werden geladen: {loaded} von {total} Teilen |
| `cases.failing_only` | Failing only | Nur fehlschlagende |
| `cases.search` | Search id or question | ID oder Frage suchen |
| `cases.back` | Back to cases | Zurück zu den Fällen |
| `cases.copy_link` | Copy link | Link kopieren |
| `cases.page` | Page | Seite |
| `shard.error` | Part {n} of the cases could not be loaded. | Teil {n} der Fälle konnte nicht geladen werden. |
| `shard.retry` | Retry | Erneut versuchen |
| `footer.no_certificate` | Supports documentation, not a compliance certificate. | Unterstützt die Dokumentation, kein Konformitätsnachweis. |
| `footer.exported` | data exported {date} | Daten exportiert {date} |
| `footer.sources` | Sources & licences | Quellen & Lizenzen |
| `notfound.title` | Page not found | Seite nicht gefunden |
| `notfound.back` | Back to runs | Zurück zu den Läufen |
| `notfound.docs` | Documentation | Dokumentation |
| `error.title` | This page could not be shown. | Diese Seite kann nicht angezeigt werden. |
| `error.reload` | Reload | Neu laden |
| `try.unavailable` | The live demo is not available in this deployment. | Die Live-Demo ist in dieser Umgebung nicht verfügbar. |
| `try.title` | Try the demo RAG app | Die Demo-RAG-App ausprobieren |
| `try.intro` | Pick a tenant. Each tenant only sees its own documents plus shared public laws. | Mandant wählen. Jeder Mandant sieht nur eigene Dokumente und öffentliche Gesetze. |
| `try.tenant` | Tenant | Mandant |
| `try.question` | Question (German) | Frage (auf Deutsch) |
| `try.examples` | Examples | Beispiele |
| `try.ask` | Ask | Fragen |
| `try.asking` | Asking… | Wird gefragt… |
| `try.cancel` | Cancel | Abbrechen |
| `try.retry` | Retry | Erneut versuchen |
| `try.hint` | Answers come from a small CPU model and can take up to a minute. | Antworten kommen von einem kleinen CPU-Modell und können bis zu einer Minute dauern. |
| `try.limits` | Limits per visitor and a shared daily budget apply. | Es gelten Limits pro Besucher und ein gemeinsames Tagesbudget. |
| `try.elapsed` | {s} s | {s} s |
| `try.answer` | Answer | Antwort |
| `try.chunks` | Retrieved chunks | Abgerufene Abschnitte |
| `try.not_in_prompt` | not sent to the model | nicht an das Modell gesendet |
| `try.invalid.empty` | Enter a question. | Bitte eine Frage eingeben. |
| `try.invalid.too_long` | At most 500 characters. | Höchstens 500 Zeichen. |
| `try.error.rate_limited` | You're asking too fast. Try again in {s} s. | Zu viele Anfragen. Bitte in {s} s erneut versuchen. |
| `try.error.busy` | The demo is busy. Try again in {s} s. | Die Demo ist ausgelastet. Bitte in {s} s erneut versuchen. |
| `try.error.daily_limit` | Daily limit reached. Try again tomorrow (00:00 UTC). | Tageslimit erreicht. Morgen ab 00:00 UTC wieder möglich. |
| `try.error.budget` | Demo quota for today is used up. Try again tomorrow (00:00 UTC). | Demo-Kontingent für heute erschöpft. Morgen ab 00:00 UTC wieder verfügbar. |
| `try.error.disabled` | The demo is paused by the maintainers. | Die Demo ist derzeit pausiert. |
| `try.error.rejected` | The request was rejected. | Die Anfrage wurde abgelehnt. |
| `try.error.timeout` | The demo took too long. Please try again later. | Die Demo hat zu lange gebraucht. Bitte später erneut versuchen. |
| `try.error.network` | Can't reach the demo server. | Der Demo-Server ist nicht erreichbar. |
| `try.error.server` | The demo had an error. Please try again. | Bei der Demo ist ein Fehler aufgetreten. Bitte erneut versuchen. |
| `try.refused` | The app declined: the documents do not answer this. | Die App lehnt ab: Die Dokumente beantworten diese Frage nicht. |
| `try.slow` | Still working — the CPU model is slow. | Läuft noch — das CPU-Modell ist langsam. |
| `try.cancelled` | Cancelled. | Abgebrochen. |

`{source}` in `summary.judged` (UI11-14) = `judge_source.<judge_mode>` (`github` or `local`). With
`judge_mode == "skipped"` the judged heading is replaced by the skipped text, so there is no source.
PR comment and report use the en labels.

`banner.judge_drift` follows D253 (R12 N3): drift = changed anchor verdicts ≥ `max(3, ceil(0.1 · n))`,
i.e. 5 of the 50 anchors, for hosted and local judges alike; it replaces the X3.4 agreement threshold.
`run.json` carries no `changed`/`n`, so the text uses the fixed wording "5 or more of 50" (= SPEC §7.6;
UI13-10). If T5.x changes the anchor count or the rule, this text changes in the same PR; the i18n
parity test covers both locales.

#### 10.4.2 Navigation, runs list, summary, tables, filters, empty states (UI9-20)

| Key | en | de |
| --- | --- | --- |
| `nav.runs` / `nav.try` / `nav.licences` | Runs / Try it / Licences | Läufe / Ausprobieren / Lizenzen |
| `nav.skip` | Skip to content | Zum Inhalt springen |
| `nav.menu` | Menu | Menü |
| `nav.main` / `nav.run` | Main / Run sections | Hauptnavigation / Laufbereiche |
| `theme.label` | Theme: {mode} | Design: {mode} |
| `theme.system` / `theme.light` / `theme.dark` | system / light / dark | System / hell / dunkel |
| `locale.switch` | Language | Sprache |
| `redirect.continue` | Weiter / Continue | Weiter / Continue |
| `runs.title` | Runs | Läufe |
| `runs.showing` | Showing {from}–{to} of {total} runs · sorted by {sort} | {from}–{to} von {total} Läufen · sortiert nach {sort} |
| `runs.col.status` / `.ref` / `.pr` / `.created` / `.tier` / `.workload` / `.cases` / `.duration` / `.cost` / `.flags` | Status / Ref / PR / Created / Tier / Workload / Cases / Duration / Cost / Flags | Status / Ref / PR / Erstellt / Stufe / Workload / Fälle / Dauer / Kosten / Hinweise |
| `runs.block_short` / `runs.judged_subset_short` | b{k} / subset | b{k} / Teilmenge |
| `runs.tier_help` | Tier 1: hosted CPU smoke run; tier 2: A40 statistical gate | Stufe 1: gehosteter CPU-Smoke-Lauf; Stufe 2: statistisches Gate auf A40 |
| `flag.incomplete` / `.judge_skipped` / `.judge_fallback` / `.judge_degraded` / `.judge_drift` | incomplete / judge skipped / judge fallback / judge degraded / judge drift | unvollständig / Judge übersprungen / Ersatz-Judge / Judge beeinträchtigt / Judge-Drift |
| `filter.status` / `.ref` / `.tier` / `.workload` / `.tenant` / `.category` / `.lang` / `.perturbation` / `.slice` | Status / Ref / Tier / Workload / Tenant / Category / Language / Perturbation / Slice | Status / Ref / Stufe / Workload / Mandant / Kategorie / Sprache / Störung / Slice |
| `filter.all` | all | alle |
| `filter.clear` | Clear filters | Filter zurücksetzen |
| `filter.count` | {n, plural, one {# result} other {# results}} | {n, plural, one {# Ergebnis} other {# Ergebnisse}} |
| `sort.label` / `sort.created` / `.status` / `.duration` / `.cost` / `.delta` / `.metric` | Sort / Created / Status / Duration / Cost / Δ / Metric | Sortierung / Erstellt / Status / Dauer / Kosten / Δ / Metrik |
| `pagination.label` / `.prev` / `.next` | Pages / Previous / Next | Seiten / Zurück / Weiter |
| `empty.runs` | No runs exported yet. | Noch keine Läufe exportiert. |
| `empty.runs_hint` | Publish runs with `pruefstand export-dashboard`. | Läufe mit `pruefstand export-dashboard` veröffentlichen. |
| `empty.filtered` | No runs match these filters. | Keine Läufe passen zu diesen Filtern. |
| `empty.cases` | No cases match these filters. | Keine Fälle passen zu diesen Filtern. |
| `empty.slices` | No slices for this dimension. | Keine Slices für diese Dimension. |
| `subnav.summary` / `.diff` / `.slices` | Summary / Diff / Slices | Übersicht / Vergleich / Slices |
| `subnav.cases` | Cases ({n} failing) | Fälle ({n} fehlschlagend) |
| `subnav.not_gated` | (not gated) | (nicht bewertet) |
| `subnav.nothing_compared` | (nothing compared) | (nichts verglichen) |
| `subnav.cases_not_published` | (cases not published) | (Fälle nicht veröffentlicht) |
| `summary.blocking` | {n, plural, one {# blocking issue} other {# blocking issues}} | {n, plural, one {# blockierendes Problem} other {# blockierende Probleme}} |
| `summary.nothing_compared` | nothing compared | nichts verglichen |
| `summary.cases_not_published` | Case details are published for the newest 20 runs only. | Falldetails werden nur für die 20 neuesten Läufe veröffentlicht. |
| `summary.likely_cause` | Likely cause: {cause} | Wahrscheinliche Ursache: {cause} |
| `summary.baseline` / `.candidate` | Baseline / Candidate | Baseline / Kandidat |
| `summary.tokens` | {n} tokens | {n} Tokens |
| `summary.judges` / `.judge_mode` | judges / judge mode | Judges / Judge-Modus |
| `summary.hard_fails` | Hard fails ({n}) | Harte Fehler ({n}) |
| `summary.gated` | Gated metrics (overall) | Bewertete Metriken (gesamt) |
| `summary.gated_slices` | Gated slices not passing | Bewertete Slices ohne PASS |
| `summary.absolute` | Absolute checks | Absolute Prüfungen |
| `summary.informational` | Informational (does not block) | Informativ (blockiert nicht) |
| `summary.judged` | Judged metrics — informational, does not block ({source}, {n} cases) | Bewertete Metriken — informativ, blockiert nicht ({source}, {n} Fälle) |
| `summary.judged_subset` | judged subset ({n} cases) | bewertete Teilmenge ({n} Fälle) |
| `summary.block` | block {k} | Block {k} |
| `judge_source.github` / `judge_source.local` | GitHub Models / local judge (A40) | GitHub Models / lokaler Judge (A40) |
| `summary.notable` | Notable slice drops (informational, does not block) | Auffällige Slice-Rückgänge (informativ, blockiert nicht) |
| `summary.not_applicable` | Not applicable | Nicht anwendbar |
| `summary.insufficient` | Insufficient data | Zu wenige Daten |
| `summary.clusters` | {n} clusters | {n} Cluster |
| `summary.top_failing` | Top failing cases | Häufigste fehlschlagende Fälle |
| `summary.open_case` | Open case | Fall öffnen |
| `summary.report_open` / `.report_download` | Open HTML report / Download HTML report | HTML-Bericht öffnen / HTML-Bericht herunterladen |
| `summary.view_diff` | View diff | Vergleich ansehen |
| `col.metric` / `.base` / `.pr` / `.delta_ci` / `.delta` / `.threshold` / `.mde` / `.max` / `.value` / `.status` / `.slice` / `.reason` / `.judged_cases` / `.check` / `.rule` / `.case` / `.evidence` | Metric / Base / PR / Δ (95% CI) / Δ / δ / MDE / Max / Value / Status / Slice / Reason / Judged cases / Check / Rule / Case / Evidence | Metrik / Basis / PR / Δ (95%-KI) / Δ / δ / MDE / Max / Wert / Status / Slice / Grund / Bewertete Fälle / Prüfung / Regel / Fall / Beleg |
| `diff.title` | Gated pairs ({testable} testable · {insufficient} insufficient data) | Bewertete Paare ({testable} prüfbar · {insufficient} zu wenige Daten) |
| `diff.no_threshold` | no threshold | keine Schwelle |
| `diff.na` | n/a | n. a. |
| `chart.show_table` / `chart.show_chart` | Show as table / Show as chart | Als Tabelle zeigen / Als Diagramm zeigen |
| `licences.title` | Sources and licences | Quellen und Lizenzen |
| `licences.col.source` / `.shown` / `.licence` / `.attribution` / `.link` | Source / Shown here / Licence / Attribution / Link | Quelle / Hier gezeigt / Lizenz / Namensnennung / Link |

#### 10.4.3 Stop reasons and data labels (de; en from `labels.json`; `stop_reason.*` in both files)

| Key | en | de |
| --- | --- | --- |
| `stop_reason.completed` | completed | abgeschlossen |
| `stop_reason.budget_exceeded` | budget exceeded | Budget überschritten |
| `stop_reason.aborted` | aborted | abgebrochen |
| `stop_reason.aborted_infra` | aborted (infrastructure) | abgebrochen (Infrastruktur) |
| `info_reason.applicable_clusters<30` | fewer than 30 clusters | weniger als 30 Cluster |
| `info_reason.refusal_outside_nightly_full` | refusal gated only in nightly full | Ablehnung wird nur im nächtlichen Volllauf bewertet |
| `info_reason.judge_uncalibrated` | judge not calibrated | Judge nicht kalibriert |
| `info_reason.judge_degraded` | judge errors above 5 % | Judge-Fehler über 5 % |
| `info_reason.judge_drift` | judge drift | Judge-Drift |
| `info_reason.tier1_judged` | tier-1 judge (informational) | Stufe-1-Judge (informativ) |
| `info_reason.tier1_deterministic_only` | reported in tier 1 | in Stufe 1 nur berichtet |
| `info_reason.tier1_injection_reported` | injection reported in tier 1 | Injection in Stufe 1 nur berichtet |
| `info_reason.judge_truncated` | judge input truncated | Judge-Eingabe gekürzt |
| `rule.canary_leak` / `rule.tenant_leak` / `rule.system_prompt_leak` | Canary leak / Tenant leak / System prompt leak (`labels.json` `hard_fail_rules` values, D273) | Canary-Leck / Mandanten-Leck / Systemprompt-Leck |
| `cause.retrieval` | (`CAUSE_MESSAGES`) | Retrieval (Chunking, Embeddings, Top-k, Reranker, Filter, Analyzer) |
| `cause.generation` | (`CAUSE_MESSAGES`) | Generierung (Prompt, Modell, Dekodierung) |
| `cause.citation_format` | (`CAUSE_MESSAGES`) | Zitierformat |
| `cause.language` | (`CAUSE_MESSAGES`) | Antwortsprache |
| `cause.refusal_policy` | (`CAUSE_MESSAGES`) | Ablehnungsverhalten |
| `cause.errors` | (`CAUSE_MESSAGES`) | Fehler des Zielsystems (Zeitüberschreitungen, Abstürze) |
| `cause.mixed` | (`CAUSE_MESSAGES`) | Gemischt (mehrere Ursachen) |

Metric labels: `labels_document().metrics` (T1.9) returns the en column, and `de.json` has the de
column, for every metric name of interfaces §5 and X3.2:

| Code | en | de |
| --- | --- | --- |
| `context_recall` | Context recall | Kontext-Recall |
| `ndcg_at_k` | nDCG@k | nDCG@k |
| `citation_precision` / `citation_recall` / `citation_f1` | Citation precision / Citation recall / Citation F1 | Zitat-Präzision / Zitat-Recall / Zitat-F1 |
| `citation_grounded` | Citation grounded | Zitat belegt |
| `evidence_recall` | Evidence recall | Beleg-Recall |
| `canary_leak` / `tenant_leak` / `system_prompt_leak` | Canary leak / Tenant leak / System prompt leak | Canary-Leck / Mandanten-Leck / Systemprompt-Leck |
| `system_prompt_similarity` | System prompt similarity | Ähnlichkeit zum Systemprompt |
| `injection_success` | Injection success | Injection-Erfolg |
| `refusal_correct` / `false_refusal` / `refusal_judged` | Refusal correct / False refusal / Refusal (judged) | Korrekte Ablehnung / Falsche Ablehnung / Ablehnung (Judge) |
| `language_match` | Language match | Sprachübereinstimmung |
| `error_rate` | Error rate | Fehlerquote |
| `latency_ms` | Latency (ms) | Latenz (ms) |
| `faithfulness` | Faithfulness | Quellentreue |
| `answer_correctness` | Answer correctness | Antwortkorrektheit |
| `perturbation_consistency` | Perturbation consistency | Konsistenz unter Störungen |

A new metric, cause, rule or reason code needs its row here and its `de.json` key in the same PR (the
label-coverage test fails otherwise).

---

## 11. Cross-surface consistency

| Section (order) | PR comment (§12) | Run summary (§4.2) | HTML report (§13) |
| --- | --- | --- | --- |
| Status + blocking count + tier | title line | status block + `TierBadge` | header |
| Refs, splits, cases, duration, cost, tokens, GPU-s (tier 2) | line 2 | meta block | header |
| Tier-1 notice | quote line (tier 1) | `Tier1Notice` | header banner |
| No-baseline notice | quote line | alert banner | header banner |
| Judge notices (skipped / fallback / degraded / drift) | quote lines | banners | header banners |
| Hard fails | first section (tier 1: check row + findings) | first section | first section |
| Table G overall (tier 2), 7 columns incl. δ, MDE | table | `MetricTable` | table |
| Table C + hard-fail row (tier 1) | table | `AbsoluteCheckTable` | table |
| Table R (tier 1) | `<details>` table | `MetricTable` reported | table |
| Table G other slices, not PASS (tier 2) | `<details>` table | table | full sortable slice table |
| Table A (tier 2) | line | `AbsoluteCheckTable` | table |
| Table I | "Informational (does not block)" line | `InformationalTable` | informational group |
| Table J | judged line or skipped line | `JudgedInfoTable` | informational group |
| Table N | one line (notable only) | one line (notable only) | informational group (all rows, notable marked) |
| Likely cause | line | status block + line | header |
| Not applicable / block G insufficient | line | line | table |
| Top failing cases | ids | links | detail cards (escaped) |
| Attribution | – (in the linked report) | footer | footer |
| Report link | footer | `ReportLink` | – |

### 11.1 Table membership: one rule for every `SliceDecision` (X5.4, UI9-05; interfaces §9)

Every `SliceDecision` in `gate.json` (`decisions`, `absolute_checks`, `notable_slices`) appears in
**exactly one** of three tables. The rule is interfaces §9 verbatim (interfaces wins). T1.9 (PR comment),
T6.4 (HTML report), T8.2a (summary) and T8.2b (diff, slices) implement this one predicate; interfaces
§9 guarantees `informational_reason is not None ⇒ gated is False`.

| Table (first match wins) | Predicate |
| --- | --- |
| **Gated** | `gated and informational_reason is None` (incl. `INSUFFICIENT_DATA` rows, shown with that status) |
| **Informational** (does not block) | `informational_reason is not None`, rendered grouped by reason code with the `LabelsDocument.informational_reasons` label |
| **Notable** | in `notable_slices` and not matched above |

A decision that matches none of the three (not gated, no reason, not in `notable_slices`) is a gate bug.
`assign_table` then returns **Informational** with the reason label `–`, never drops it, and the
renderer tests assert that this never happens on fixture data.

Reason codes (interfaces §9; labels §10.4.3): `applicable_clusters<30`, `refusal_outside_nightly_full`,
`judge_uncalibrated`, `judge_degraded`, `judge_drift`, `tier1_judged`, `tier1_deterministic_only`
(every paired metric of a `stack == "live"` run, X5.6), `tier1_injection_reported` (tier-1
`injection_success`, X3.11), `judge_truncated` (X3.9). Unknown codes render with the raw code.

Blocks inside the three tables (letters used by §4.2, §12, §13). Blocks never move a row to another
table; they only lay out rows of one table.

| Block | Rows | Tier 2 | Tier 1 |
| --- | --- | --- | --- |
| **G** | Gated, from `decisions` | 7-column `overall` table; other dimensions; insufficient line | (none expected: every tier-1 paired metric carries `tier1_deterministic_only`; rows present anyway render as G) |
| **A** / **C** | Gated, from `absolute_checks` | **A** Absolute checks | **C** Checks (decide), after the hard-fail row (in practice `error_rate`); on the Slices page the Gated group titled `tier1.checks` (§4.4) |
| **R** | Informational with reason `tier1_deterministic_only`, `tier1_injection_reported` or `applicable_clusters<30` | part of **I** | "Reported — does not decide at n = N" table |
| **J** | Informational with reason `tier1_judged` | part of **I** | Judged table / line |
| **I** | every other Informational row | all Informational rows | the rest (e.g. `refusal_outside_nightly_full`, `judge_*`) |
| **N** | Notable | notable line / informational slice group | same |

Rendering per block:
- **G**: `overall` rows with status ≠ `INSUFFICIENT_DATA` → the 7-column table; other dimensions →
  "Gated slices not passing" (summary, PR) or all rows (diff, slices page, report); `INSUFFICIENT_DATA`
  rows → the "Insufficient data" line as `<metric label> · <dimension>=<value> (<n_clusters> clusters)`
  (summary, PR) or greyed rows (diff, report).
- **A** / **C**: Metric · Value (`candidate_mean`) · Max (`max_value`) · Status.
- **R**: Metric · Base · PR · Δ · MDE · Max · Reported because (reason label).
- **I**: Metric (+ `dimension=value` unless `overall`) · Base · PR · Δ · Reason (label).
- **J**: Metric · Base · PR · Δ · Judged cases; replaced by the skipped text when
  `judge_mode == "skipped"`.
- **N**: `dimension=value` Δ, marker when `notable`.
- Rows of R, I and J never show a status word (informational pairs are PASS by definition and must not
  read as passing).
- A surface may omit rows inside a block, but it never shows a row twice and never drops a block that
  has rows. The complete list of omissions (UI11-12):
  - PR comment, block N: only `notable == true` rows;
  - PR comment, block G outside `overall`: only non-PASS rows;
  - PR comment, block A (tier 2): only non-PASS rows on the `Absolute checks:` line; when every block-A
    row is PASS, the line is `Absolute checks: all PASS (<n>)`. Block C (tier 1) always shows every row.
  - PR comment, block I: reason-less `absolute_checks` slice rows are omitted (shown on the notable line when `notable == true`; D387);
  Renderer tests count an omitted row as "accounted for" only under one of these rules.
- `no_baseline == true`: no block is rendered (nothing was compared). Hard fails are rendered when
  present.
- **No baseline run available (Y7.4, UI11-08).** `render_pr_comment` and `render_html` take
  `base: … | None` (interfaces §10). `base is None` iff `no_baseline`, or the baseline run is not in
  the renderer's input (store-only baseline on the executor; `export-dashboard` with a baseline outside
  `--runs`). Then: refs line `Baseline: –` (or `baseline_run_id` in mono when only the id is known);
  Base and Δ columns show `–` unless the value comes from `SliceDecision` (Base = `baseline_mean`,
  Δ = `result.mean_diff`, both from `gate.json`, so they still render); no baseline answers in case
  cards; no baseline manifest in the report's Run metadata (`–`).

`DashboardSliceRow.kind` (interfaces §10.1) is a data field with its own rule: `absolute_checks` →
`absolute`; `notable_slices` and decisions with `informational_reason` → `informational`; other
decisions → `decision`. The slices page groups by this table rule, not by `kind` alone (§4.4).

---

## 12. PR comment layout (T1.9)

Fixed order; omit an empty section (and its heading) except title, refs and the main table. Variant by
`cand.stack`: `a40` → §12.1, `live` → §12.2 (W1.3, W1.4, X5.6). Table letters refer to §11.1.

### 12.1 Tier 2 (statistical gate, status `pruefstand/gate`)

```markdown
<!-- pruefstand:pr-comment -->
## Prüfstand: ❌ FAIL (2 blocking issues)
Baseline: main@a1b2c3d · Candidate: pr-42@d4e5f6a · core, robust_pr · 790 cases · 18m 12s · 0 USD · 4.1 M tokens · ~2,100 GPU-s
> ⚠️ Judge drift detected (5 or more of 50 anchor verdicts changed); judged metrics are informational until the flag clears.

### 🚨 Hard fails (1)
| Rule | Case | Metric | Evidence (redacted) |
|---|---|---|---|
| canary_leak | law-0107 | canary_leak | `… CANARY-**-****** …` |

| Metric | Base | PR | Δ (95% CI) | δ | MDE | Status |
|---|---|---|---|---|---|---|
| Context recall | 0.86 | 0.77 | −0.09 (−0.12, −0.06) | 0.05 | 0.06 | FAIL |
| Faithfulness | 0.91 | 0.90 | −0.01 (−0.03, +0.01) | 0.05 | 0.07 | PASS |

<details><summary>Gated slices not passing (3)</summary>

| Slice | Metric | Base | PR | Δ (95% CI) | δ | MDE | Status |
|---|---|---|---|---|---|---|---|
| tenant=kanzlei_mueller | Context recall | 0.84 | 0.77 | −0.07 (−0.11, −0.03) | 0.05 | 0.10 | WARN |
</details>

Absolute checks: Injection success 0.03 (max 0.02) WARN
Informational (does not block): Answer correctness 0.80 → 0.78 (−0.02) — judge drift
Notable slice drops (informational): perturbation=compound_split −0.18, category=cross_lingual −0.09
Likely cause: retrieval — Retrieval (chunking, embeddings, top-k, reranker, filter, analyzer)
Not applicable: answer_correctness (12 cases) · Insufficient data: Context recall · tenant=stadtwerke_sued (22 clusters)
Top failing cases: law-0042, law-0107, xl-0013

<sub>[Full report](<report_url>) · pruefstand vX.Y.Z · WARN does not block unless --fail-on-warn</sub>
```

### 12.2 Tier 1 (hard fails + error rate decide, `live-e2e / gate`; X5.6, X3.11)

```markdown
<!-- pruefstand:pr-comment -->
## Prüfstand tier 1: ✅ PASS (0 blocking issues)
Baseline: main@a1b2c3d · Candidate: pr-42@d4e5f6a · smoke_live · 20 cases · 14m 03s · 0 USD · 200 k tokens
> ℹ️ Tier 1 decides on hard fails and the error rate only. Language, citation, refusal and injection results are reported. Paired statistics need ≥ 30 clusters and run in tier 2 (`pruefstand/gate`).

| Check | Value | Max | Status |
|---|---|---|---|
| Hard fails (canary, tenant, system prompt) | 0 | 0 | PASS |
| Error rate | 0.00 | 0.02 | PASS |

<details><summary>Reported, does not decide at n = 20 (4)</summary>

| Metric | Base | PR | Δ | MDE | Max | Reported because |
|---|---|---|---|---|---|---|
| Language match | 1.00 | 0.95 | −0.05 | 0.21 | – | reported in tier 1 |
| Citation F1 | 0.90 | 0.90 | +0.00 | 0.24 | – | reported in tier 1 |
| False refusal | 0.00 | 0.00 | +0.00 | – | – | reported in tier 1 |
| Injection success | 0.00 | 0.00 | – | – | 0.02 | injection reported in tier 1 |
</details>

Informational (does not block): Refusal correct 1.00 → 1.00 (+0.00) — refusal gated only in nightly full
**Judged metrics (informational, does not block; GitHub Models, 10 cases):** Faithfulness 0.88 → 0.85 (−0.03) · Answer correctness 0.91 → 0.90 (−0.01)
Top failing cases: law-0042

<sub>[Full report](<report_url>) · pruefstand vX.Y.Z · statistical gate: tier 2</sub>
```

- `judge_mode == "skipped"` → the judged line becomes
  `> ℹ️ Judge skipped (quota used up). Judged metrics are not shown; the deterministic gate still decided.`
- Hard fails present → the §12.1 hard-fail table comes first and the check row shows the count + FAIL.
- Block R rows: Δ = `result.mean_diff` when `result` is present, else `–`; CI omitted on purpose; never
  computed in `report`. "Judged … 10 cases" = `cand.judged_cases`.

### 12.3 Rules (both variants)

- Status words in tables uppercase (`PASS`/`WARN`/`FAIL`/`INSUFFICIENT`); SPEC §7.6 lowercase `pass`
  is a typo fixed by T1.9 (UI-19).
- Title emoji (the complete list; T1.9 uses exactly this): ✅ PASS, ⚠️ WARN (also UNSUPPORTED_CONFIG),
  ❌ FAIL, ◌ INSUFFICIENT DATA, ⚪ NO BASELINE; the word always present.
- Block A on tier 2: `Absolute checks: <non-PASS rows>`, or `Absolute checks: all PASS (<n>)` (§11.1).
- `base is None` → `Baseline: –` (or `baseline_run_id` in mono) on the refs line (§11.1, UI11-08).
- **No baseline** (`GateReport.no_baseline == true`, `baseline_run_id == null`; X5.5): title
  `## Prüfstand: ⚪ NO BASELINE (nothing compared)` (tier 1: `## Prüfstand tier 1: ⚪ NO BASELINE (nothing compared)`),
  then the refs line with `Baseline: –`, then
  `> ❌ No baseline for <eval_fingerprint>; run baseline-promote. Nothing was compared.`; hard fails
  if present; no metric tables (§11.1). Never ✅. The commit status is `failure` (interfaces §10).
- δ = `SliceDecision.max_drop`, Max = `SliceDecision.max_value` (W5.2); `None` → `–`. MDE on every gated
  row (W3.6).
- Judge notice lines, in this order, each only when true: `judge_mode == "skipped"`,
  `judge_fallback`, `judge_degraded`, `judge_drift` (texts = §10.4 en). Never silent.
- Block I: every row is on the "Informational (does not block): …" line with its reason label, in
  both tiers.
- `Not applicable:` from `GateReport.not_applicable_counts` as `metric (n cases)`, comma-separated;
  omitted when empty (also in the SPEC §7.6 example, UI9-15).
- Refs line (UI9-14): ref labels per §2.2; tokens = `prompt_tokens + completion_tokens`; GPU-s only for
  tier 2. **Block / judged subset (UI13-19):** `cand.block` set → the splits part reads
  `<splits> block <k>` (e.g. `… · Candidate: main@a1b2c3d · full block 1 · 1500 cases · …`);
  `cand.judged_subset` true → the judged lead-in ends with `judged subset (150 cases)` (tier 2: before
  the judged rows on the informational line; tier 1: inside the bold judged line). Both copied from
  `run.json`.
- The comment never names a label as the way to (re)start the gate (P1.2: tier 2 is started only by a
  `workflow_dispatch` of `gate-executor.yml`); no text mentions `run-gate`.
- `<details>` wraps any section with > 5 rows (and block R always); case-derived strings still pass
  `md_escape`.
- `report_url is None` → no "Full report" link; append "(full report in the private executor run)"
  after the top failing cases (SPEC §7.6).
- Size guard (60 000 chars): truncate the slice table first, then top failing cases.

---

## 13. HTML report layout (T6.4)

Single file, inline CSS from §7 tokens (light + dark via `prefers-color-scheme`), no external
requests, optional ≤ 5 kB inline JS for sorting kept in `report/templates/_sort.js` and inlined
verbatim. `render_html` writes the report's own CSP `<meta>` with the sha256 of those bytes (§7.4 item
2). `base` may be `None` (§11.1, UI11-08). Published copy =
`data/runs/<id>/report.html`, written by `export-dashboard` (T8.1) through `render_html` on
`sanitise_run` output (W5.3, UI-06); private executor artefacts keep the full render.

```text
<header>  Prüfstand report · STATUS badge (⚪ NO BASELINE when no_baseline) · Tier 1|2 · n blocking · likely cause
          refs · splits (+ "block <k>" for a nightly) · cases · duration · cost · tokens · GPU-s (tier 2) · created (UTC)
          banners: incomplete / no baseline / tier-1 notice / judge skipped|fallback|degraded|drift /
                   "supports documentation, not a compliance certificate"
<nav>     TOC: Hard fails · Metrics · Slices · Absolute checks · Informational · Failing cases · Run metadata
<section> Hard fails (redacted evidence, lang=de)
<section> Metrics (tier 2: block G overall, 7 columns; tier 1: hard-fail row + block C, then block R) — §12 formats
<section> Slices: block G (all dimensions, insufficient greyed), then block N (caption "informational, does not block", notable marked), sortable
<section> Absolute checks (block A, tier 2)
<section> Informational — blocks I and J (or the skipped text; block J caption + "judged subset (150 cases)" when judged_subset, UI13-19); judge truncation: `counts.judge_truncated` and the truncated case ids (X3.9)
<section> Top failing cases (≤ 20): card per case — question, answer (escaped, lang={case lang}, pre-wrap), citations (lang=de),
          chunk list (public: ids + tenant badges; private: chunk text in <details>, lang=de; "not used in prompt" when used_in_prompt == false)
<section> Run metadata: <dl> of both manifests (models, judges, judge_mode, prompt versions, fingerprints, SHAs)
<footer>  footer_line.en from report/templates/_licences.json (same text as the dashboard footer, §4.7) + sources list, pruefstand version
```

Rules: `<html lang="en">`; German data `lang="de"`, questions/answers the case's `lang`; every table
has `<caption>` and `scope`; sortable headers are `<button>` with `aria-sort`, default order meaningful
without JS; `@media print` hides TOC and sort buttons, avoids breaks inside cards, prints light; max
width 1100 px; status never colour alone; §10.2 formats; table membership §11.1; < 2 MB for 1,500
cases; axe 0 serious/critical (T8.3 runs it on the export).

---

## 14. Fixtures and UI test coverage (W5.6, X1.2; T8.1, T8.3, T8.4)

### 14.1 Fixture sets and fixture states

`apps/dashboard/fixtures/` holds **two sets**, each a complete data tree in the §2.3 layout, built and
tested as its own site (X1.2, UI-13, UI9-01):

| Set | Content | Used for |
| --- | --- | --- |
| `fixtures/populated/` | every `F-*` and `D-*` fixture below in one `runs/index.json`, plus `labels.json`, `manifest.json`, `SOURCE.md` | every page × state except `L-EMPTY` |
| `fixtures/empty/` | `runs/index.json` with 0 runs, `labels.json`, `manifest.json`, `SOURCE.md` (derived from `populated`) | `L-EMPTY`; root redirect, licences, 404 on an empty site |

Everything lives under `apps/dashboard/fixtures/**` (raw-data allowlist, CLAUDE.md §9; Y7.3, UI11-04):

```text
apps/dashboard/fixtures/raw/<run_id>/     real tier-1 run dirs (public slice only): run.json, results.parquet,
                                          responses.jsonl, llm_calls.parquet, gate.json; plus the derived raw runs
apps/dashboard/fixtures/populated/        export-dashboard output of raw/ + derive_fixtures.mjs output
apps/dashboard/fixtures/empty/
scripts/dashboard/derive.py               raw-level derivations (below); deterministic, documented in SOURCE.md
scripts/dashboard/tests/test_derive.py    its tests (inside the pytest testpaths and the `scripts` import root)
```

The script lives under `scripts/dashboard/` (N6.5, UI12-17, DEV12-06) so that it is type-checked and
its tests run in `make test`; its **outputs** stay under `apps/dashboard/fixtures/**`.

Pipeline (`scripts/dashboard/refresh_snapshot.sh`, one command):
1. download the real tier-1 artefacts (`live-e2e.yml` run ids; T8.3 adds `--dashboard-data <ref>` for
   tier-2 runs) into `fixtures/raw/<run_id>/`;
2. `uv run python scripts/dashboard/derive.py` writes the **raw-level derived runs** from real runs,
   always through real pruefstand code (Y7.3, UI11-03). Without arguments it regenerates all three;
   `--partial`, `--no-baseline`, `--judge-skipped` select one (`--raw <dir>` defaults to
   `apps/dashboard/fixtures/raw`; it reads and writes only inside that dir):
   - `F-PARTIAL`: copy of the `F-T1` raw run, truncated to its first 5 cases (`results.parquet`,
     `responses.jsonl`, `llm_calls.parquet`), `complete=false`, `stop_reason="budget_exceeded"`, no
     `gate.json`;
   - `F-NO-BASELINE`: copy of `F-T1`; then the **Python API** of the `--from-store` path (the `gate`
     CLI has no `--config`, so the store cannot be chosen from the command line; UI13-14): `cfg` = the
     run's config with `baseline_store = BaselineStoreConfig(type="local_dir", path=<tmp>,
     data_root=<tmp>)` for an **empty** temp dir, the same store lookup the CLI uses
     (`build_baseline_store(cfg.baseline_store)`, finds nothing), then `run_gate(candidate, None, cfg)`
     and `write_gate_json`, which writes the real `no_baseline` `gate.json` (T8.1 names the exact
     functions); nothing is written outside the temp dir and the raw dir;
   - `F-JUDGE-SKIPPED`: copy of `F-T1` with `judge_mode="skipped"`, `judged_cases=0` and the judged
     metric values removed; then `pruefstand gate --candidate <copy> --baseline <F-BASE raw>`;
   - each derived run gets a new deterministic run id (`RunId` format, seeded from source id +
     derivation name). Re-running `derive.py` on the same inputs is byte-identical;
3. `pruefstand export-dashboard --runs apps/dashboard/fixtures/raw --out apps/dashboard/fixtures/populated`;
4. `scripts/dashboard/derive_fixtures.mjs` writes the exported-level `D-*` fixtures from the real
   files (new run ids, never hand-written).

`SOURCE.md` lists run ids, SHAs, date, state ids, the exact command of every derivation, and the
refused / error / `en` case ids. Both sets pass `validate_data.mjs` (§2.4); nothing invalid is committed.

| Fixture | State(s) | Source | Added by |
| --- | --- | --- | --- |
| `F-BASE` | `S-NOT-GATED` | tier-1 `live-baseline` run on `main` | T8.1 |
| `F-T1` | `S-TIER1`, `S-PASS` (tier 1), `judge_mode=github` (≤ 10 judged, block J rows), block R incl. `injection_success` (`tier1_injection_reported`) | tier-1 `live-e2e` PR run (`smoke_live`) | T8.1 |
| `F-HARD-FAIL` | `S-HARD-FAIL` (tier 1), leak chunk | tier-1 `scenarios` leg `tenant_filter: post_topk` | T8.1 |
| `F-PARTIAL` | `S-PARTIAL` (`complete=false`, no gate) | `derive.py` from `F-T1`: truncated, `budget_exceeded` | T8.1 |
| `F-JUDGE-SKIPPED` | `S-JUDGE-SKIPPED` | `derive.py` from `F-T1`: `judge_mode=skipped`, judged values dropped, re-gated vs `F-BASE` (W1.4) | T8.1 |
| `F-NO-BASELINE` | `S-NO-BASELINE` (`no_baseline=true`, `baseline_run_id=null`, `RunIndexEntry.no_baseline=true`); its `report.html` is rendered with `base=None` (UI11-08) | `derive.py` from `F-T1`: the real `--from-store` code path (`run_gate(candidate, None, cfg)` with an empty `local_dir` store) | T8.1 |
| `F-PASS` | `S-PASS` (tier 2) | tier-2 main/nightly run from `pruefstand-dashboard-data` (W2.9) | T8.3 |
| `F-WARN` | `S-WARN` (tier 2) | tier-2 run (T6.5 demo PR or absolute-check WARN) | T8.3 |
| `F-FAIL` | `S-FAIL` (tier 2, statistical), `S-INSUFFICIENT`, blocks G, A, I, N with rows | tier-2 run of the reranker-off / no-citation scenario (W1.5) | T8.3 |
| `D-T2-HARD-FAIL` | `S-HARD-FAIL` (tier 2 hard-fail panel) | from `F-FAIL`: adds `F-HARD-FAIL`'s `tenant_leak` finding and its `DashboardCase` (shard 0, R4 order kept, id added to `top_failing_cases`) | T8.3 |
| `D-JUDGE-FLAGS` | `S-JUDGE-FALLBACK`, `S-JUDGE-DEGRADED`, `S-JUDGE-DRIFT`, `S-UNSUPPORTED` (four runs) | from `F-PASS`: one flag per run (`UNSUPPORTED_CONFIG` status for the fourth) | T8.3 |
| `D-BASELINE-MISSING` | `S-BASELINE-MISSING` | copy of `F-T1` whose `baseline_run_id` is replaced by a new id that is not in the index | T8.1 |
| `D-MANY` | pagination (≥ 60 runs in the index), `C-LOADING` / `C-SHARD-ERROR` and Lighthouse on one run with 1,500 cases (3 shards of 500), `S-CASES-PRUNED` (the clones outside the newest 20; a pruned run **with** hard fails is covered by the Vitest case `HardFailList.test.tsx`, UI13-16), workload cells `nightly · b<k>` and `pr · subset` (clones with `block` / `judged_subset` set, UI13-19) | real runs and cases cloned with new ids and full run dirs; the 1,500-case run is dated newer than every other fixture run; every other clone is dated **older** than all `F-*`/`D-*` runs. `derive_fixtures.mjs` applies the §2.3 rule exactly (newest 20 keep `cases/` and `report.html`), so the 16 `F-*`/`D-*` runs and the 1,500-case run are always case-published and ≥ 40 clones are `S-CASES-PRUNED` | T8.1 |
| `D-EMPTY` | `L-EMPTY`, `E-PLACEHOLDER` (`/de/runs/_empty/` builds and renders `empty.runs`) | the whole `fixtures/empty/` set | T8.1 |

Removed in v3: `D-BAD-SCHEMA` (invalid data now fails the build; tested in `validate-data.test.ts` on
temp copies, never committed), `D-SHARD-MISSING` (shard error is produced by network failure, §14.2),
`D-NO-BASELINE` (renamed `D-BASELINE-MISSING`, UI9-16).

`scripts/dashboard/check_fixture_states.mjs` fails if:
- a state id of this table has no fixture (T8.1 allow-lists the four T8.3 rows until T8.3 lands);
- `populated` has no failing case with `refused == true`, none with `error != null`, or no case with
  `lang == "en"` (UI9-12, UI9-16). `refresh_snapshot.sh` picks real runs until these exist and records
  them in `SOURCE.md`. The refused and error cases are tested in the cases panel, so they need not be
  failing.

CI (`ui.yml` job `fixtures`, T8.1): both sets pass `validate_data.mjs`; `check_fixture_states.mjs`;
`SOURCE.md` date ≤ 30 days (informational until M7, UI-15).

### 14.2 Test matrix: page × state × theme × locale × viewport

**Builds and projects (X1.2).** `scripts/dashboard/build_set.sh populated` and `… empty` build two
sites into `apps/dashboard/.sets/{populated,empty}/`. `playwright.config.ts` has two `webServer`
entries (`serve .sets/populated -l 4173`, `serve .sets/empty -l 4174`, each with the header-free
`serve.json` of §7.4 item 4) and one project per set and viewport; the `basePath` project has its own
build and server (below):

| Project | Set | Viewport | When |
| --- | --- | --- | --- |
| `populated-360`, `populated-1280` | populated | 360×740, 1280×800 (Chromium) | every UI PR |
| `empty-360`, `empty-1280` | empty | same | every UI PR |
| `{populated,empty}-webkit-1280`, `{populated,empty}-mobile-chromium` (Pixel 7), `{populated,empty}-mobile-webkit` (iPhone 14) | both | device presets | nightly |
| `populated-basepath-1280` | populated, built with `NEXT_BASE_PATH=/pruefstand` (`.sets/populated-bp`) | 1280×800 (Chromium, light, `de`) | every UI PR (job `basepath-smoke`, N5.5) |

**`basePath` smoke (N5.5, UI12-05, UI12-06).** The required PR job `basepath-smoke` (in `ui.yml`, part
of `ui / check`) runs `build_set.sh populated --out populated-bp` with `NEXT_BASE_PATH=/pruefstand`,
then `scripts/dashboard/serve_under_base.sh .sets/populated-bp /pruefstand <tmp>` and serves `<tmp>` on
port 4177. The helper makes `<tmp>/pruefstand/` = the site, copies the site's `404.html` to
`<tmp>/404.html` (GitHub Pages serves the **site-root** 404 for the whole project path) and writes
`<tmp>/serve.json` (`{"cleanUrls": false, "trailingSlash": true}`, no headers). `e2e/basepath.spec.ts`
(project `populated-basepath-1280`, `baseURL` `http://localhost:4177/pruefstand/`) checks: `/pruefstand/`
→ `de/`; runs list; the `F-FAIL` summary and its report link (opens `report.html`, status 200, its own
CSP meta); the `D-MANY` 1,500-case cases list with shard 1 loaded; one static case page; an unknown path
→ the 404 page with status 404 and the `notfound.docs` link to `/pruefstand/docs/`; `theme-init.js`
loads; **every same-origin request of every page starts with `/pruefstand/`** (a hard-coded `/data/…` or
`/_next/…` fails the PR); no CSP violation, exactly one CSP meta. T8.5's local smoke uses the same helper.

`e2e/matrix.ts` exports `{page, state, set, fixtureRunId, path, expect}`; each project runs the rows of
its set × {light, dark} × {de, en}, so every row runs in **8 combinations** (2 projects × 4).
Per combination: state assertions (expected text by i18n key, banner, landmarks), axe with 0
`serious`/`critical`, no page-level horizontal scroll, `lang` checks, footer attribution present, no
CSP violation and exactly one CSP `<meta>` (§7.4), and, in the nightly job only, a visual screenshot
(UI9-18). Query-driven rows wait for `[data-hydrated]` first (§6).

**Network rules (X1.2).** No mocks. `page.route` is allowed **only to delay** a real response (the
handler awaits a test-controlled promise, then calls `route.continue()`), never to change, fulfil or
abort it. `e2e/delay.ts` is the only file that calls `page.route` (T8.3). Network failure is produced
with `context.setOffline(true)` (browser offline emulation, not interception).

**`C-SHARD-ERROR` mechanics (UI11-18).** Playwright does not document whether `route.continue()` of a
request intercepted before `setOffline(true)` fails. T8.3 first runs a one-off probe and records the
result in `decisions.md`, then uses exactly one of:
- **primary** (if the probe shows the continued request fails offline): shards 1+ delayed →
  `setOffline(true)` → release → shard error asserted → `setOffline(false)` → Retry → shard loaded;
- **fallback** (if it passes through): shard 1 is held by the delay longer than the loader's
  `SHARD_TIMEOUT_MS` (§4.5.1), so the loader aborts it → shard error asserted → release → Retry → shard
  loaded. This uses delay only and no offline emulation.
The negative control (T8.3) shows that the chosen mechanism really produces the error (the test fails
when the delay is removed).

| Page | Set | States (fixture) |
| --- | --- | --- |
| Root redirect | both | `/` → `/de/` (meta refresh); the link is present |
| Runs list | populated | `L-POPULATED` (page 1 and page 3), `L-FILTERED-EMPTY` (`?status=unsupported_config&tier=1`), `S-NO-BASELINE` row badge, flags |
| Runs list | empty | `L-EMPTY`; `E-PLACEHOLDER` (`/de/runs/_empty/` renders `empty.runs`, `noindex`, not linked from the list) |
| Placeholders | empty | `E-PLACEHOLDER`: `/de/runs/_empty/diff/`, `/de/runs/_empty/slices/`, `/de/runs/_empty/cases/` (`empty.runs`, `noindex`, footer, CSP; UI12-18) |
| Placeholders | populated | `E-PLACEHOLDER`: `/de/runs/<F-PASS id>/cases/_empty/` (`empty.cases`, `noindex`, not linked; UI12-18) |
| Run summary | populated | `S-PASS`, `S-WARN`, `S-FAIL`, `S-HARD-FAIL` (`F-HARD-FAIL` and `D-T2-HARD-FAIL`), `S-TIER1`, `S-PARTIAL`, `S-JUDGE-SKIPPED`, `S-NOT-GATED`, `S-NO-BASELINE` (sub-nav "(nothing compared)"), `S-JUDGE-FALLBACK`, `S-JUDGE-DEGRADED`, `S-JUDGE-DRIFT` (D253 text), `S-UNSUPPORTED`, `S-BASELINE-MISSING`, `S-CASES-PRUNED` (oldest `D-MANY` clone: sub-nav "(cases not published)", no report link, no `Open case` link), meta block `block <k>` and `judged subset (150 cases)` on the `D-MANY` clones that carry them (UI13-19) |
| Diff | populated | `S-FAIL`, `S-WARN`, `S-PASS`, `S-TIER1`; `S-NO-BASELINE` → `/de/runs/<F-NO-BASELINE id>/diff/` is the 404 page (UI11-20) |
| Slices | populated | `S-FAIL` (gated + informational + notable), `S-PASS`, `S-TIER1` (three sections: `tier1.checks` with `error_rate` and its status word, `tier1.reported`, informational; UI11-01) |
| Cases list (panel ≥ 1024, full-width < 1024) | populated | `S-HARD-FAIL` (leak), `S-FAIL`, `S-PASS` (no failing → all), `S-NOT-GATED`, `S-BASELINE-MISSING`, `C-LOADING` (`D-MANY` 1,500-case run; shards 1+ delayed by `e2e/delay.ts` until the assertions ran), `C-SHARD-ERROR` (same run; mechanism above), `C-NOT-FOUND` (`?case=unknown`), refused case and error case in the panel (`?case=<id>` from `SOURCE.md`), one `en` case (`lang="en"` on question and answers) |
| Static case page | populated | `S-HARD-FAIL` leak case (tier 1 and tier 2); `S-FAIL` case with citations and a `not_applicable` metric |
| Licences | both | default |
| 404 | both | `X-404`: `/de/runs/does-not-exist/`, `/en/runs/<id>/cases/<passing case id>/`, `/fr/` → `404.html` content, status 404; populated also `/de/runs/<S-CASES-PRUNED id>/cases/`; no `notfound.docs` link (empty `basePath`) |
| `report.html` | populated | `S-FAIL`, `S-TIER1`, `S-JUDGE-SKIPPED`, `S-NO-BASELINE` (light/dark × 360/1280 = 4 combinations; English only; its own CSP meta) |
| Try it (T8.4; nightly on the VM, real demo stack) | `populated-try`, `populated-try-timeout` | `T-IDLE`, `T-INVALID`, `T-LOADING`/`T-SLOW`, `T-CANCELLED`, `T-SUCCESS`, `T-REFUSED`, `T-TIMEOUT`, `T-RATE-LIMITED`, `T-BUSY`, `T-DAILY-LIMIT`, `T-BUDGET`, `T-DEMO-OFF`, `T-NETWORK` (Try-it run below) |
| Try it | populated (no demo URL, every UI PR) | `T-DISABLED` (no nav link, `try.unavailable`). `T-REJECTED`, `T-SERVER-ERROR`: Vitest reducer only (the UI cannot produce them against a correct server) |

**Try-it run (Y7.5, UI11-07, N5.4, UI12-04, UI12-11, UI12-12).** Runs nightly on the VM (job
`demo-e2e` of the private executor workflow `demo-nightly.yml`, after `demo-deploy`, 06:15
Europe/Berlin, after the night window; T8.5, D244) and on demand by `scripts/demo/try_e2e.sh` (T8.4).
It is **never** a `ui.yml` job or a PR check (no `try-it` job exists in `ui.yml`; UI12-10).
- **Toolchain:** `try_e2e.sh` runs `pnpm install --frozen-lockfile`, both builds and Playwright inside
  the pinned Playwright image (the one used for visual baselines) with `--network host`, mounting the
  job's disposable checkout of trusted `main`. The service user `pruefstand` needs only Docker, no
  Node, pnpm or browsers (UI12-12).
- **Ports:** `E2E_PORT = 8091 + ${PORT_OFFSET:-0}` (`PORT_OFFSET=10000` on an agent dev stack → 18091);
  the script uses it for the compose port and for `NEXT_PUBLIC_DEMO_API_URL=http://127.0.0.1:$E2E_PORT`.
  The site is served on 4175. The public demo `rag-demo` stays on `127.0.0.1:8090`; `embed` has no
  host port (UI12-11).
- **Builds:** `build_set.sh populated --out populated-try` with `NEXT_PUBLIC_DEMO_API_URL` as above, and
  `build_set.sh populated --out populated-try-timeout` with the same URL and `NEXT_PUBLIC_DEMO_TIMEOUT_S=1`.
  `populated-try` is served on 4175 for every group; for `T-TIMEOUT` (run last) the script stops it and
  serves `populated-try-timeout` on 4175, so both have the one CORS origin
  `DEMO_ALLOWED_ORIGIN=http://localhost:4175`.
- **One demo instance:** `rag-demo-e2e` (compose project `pruefstand-demo`, profile `e2e` in
  `infra/deploy/demo/compose.yml`, published only on `127.0.0.1:$E2E_PORT`) shares the demo's Qdrant,
  `llm` and `embed`; the public `rag-demo` is never touched. Its env adds `TRUSTED_PROXY_HOPS=0` (the
  browser and the test call it directly, so the client key is the peer address rag-demo sees, which for
  host connections through the published port is the Docker bridge gateway, stable for the run;
  UI13-04) and `DEMO_TEST_RESET=1`.
- **Reset before every combination (N5.4, P5.4):** with `DEMO_TEST_RESET=1` rag-demo registers
  `POST /v1/_test/reset`, which empties the token buckets, daily counters, the token/request budget and
  the concurrency slots and returns 204. It answers only when the TCP peer is loopback (`127.0.0.1` /
  `::1`; `X-Forwarded-For` is ignored), else 404; without the env the route does not exist (404). The
  `demo` profile never sets the env. While a generation is in flight it returns **409** and changes
  nothing (UI13-15). A host request to the published port is never loopback inside the container, so
  **`try_e2e.sh` calls it from inside the container** before each test (row × combination):
  `docker compose -p pruefstand-demo exec -T rag-demo-e2e curl -fsS -X POST http://localhost:8000/v1/_test/reset`
  (retry on 409 for ≤ 60 s), then runs that one test with `docker exec` in a long-lived Playwright
  container (`-g '<exact title>' --project <p>`). `try.spec.ts` itself never calls the reset. So **each
  of the 8 combinations** of a row starts from empty limits.
- **Groups (env changes only):** rows are grouped by the env they need (defaults; `DEMO_RATE_PER_MIN=1`;
  `DEMO_MAX_CONCURRENCY=1`; `DEMO_DAILY_PER_KEY=1`; `DEMO_DAILY_REQUESTS=0`; `DEMO_ENABLED=false`;
  stopped). Before each group `try_e2e.sh` restarts `rag-demo-e2e` with that env and waits for
  `/v1/health`. `try.spec.ts` runs with `workers: 1`, `fullyParallel: false`.
- **Limit rows without a page-side success (UI12-04):** after the reset, `T-RATE-LIMITED` and
  `T-DAILY-LIMIT` first send **one real pre-request** with Playwright `request.post` (same client key);
  the page's first request then gets `rate_limited` / `daily_limit`. `T-BUSY`: one real query is sent
  with `request.post` and, once the server has accepted it, the page submits while it still runs; its
  `afterEach` awaits that background request to completion, so the next reset finds the instance idle
  (UI13-15).
  `T-BUDGET` (`DEMO_DAILY_REQUESTS=0`) and `T-DEMO-OFF` need no generation.
- **Timing-free states:** `T-LOADING`, `T-SLOW` and `T-CANCELLED` hold the real `/v1/query` response
  with `e2e/delay.ts` (delay only, X1.2), so they never depend on model speed. Real generations run in
  `T-SUCCESS`, `T-REFUSED`, `T-BUSY` and the one pre-request of `T-RATE-LIMITED` and `T-DAILY-LIMIT`:
  5 × 8 = 40 per night.
- **Budget:** builds ≤ 8 min, 7 restarts ≤ 4 min, 40 real generations at ≤ 30 s ≤ 20 min, the other
  combinations (incl. 8 × 11 s for `T-SLOW`) ≤ 8 min, one in-container reset + one `docker exec` per
  test (≈ 104 × ≤ 2 s) ≤ 4 min → ≤ 44 min wall time; the workflow job has `timeout-minutes: 45`.
  `try_e2e.sh` prints the wall time, the rows × combinations count and the number of resets.

Not in Playwright: `X-ERROR` (Vitest renders `error.tsx` with each error class); `B-INVALID-DATA`
(`validate-data.test.ts`: on temp copies of `populated`, a `schema_version: "2"` run, a missing shard,
`gate.json` without `report.html`, an index entry without a run dir → each fails with the file named).

### 14.3 Where each layer runs

| Layer | Scope | When |
| --- | --- | --- |
| Vitest | every component variant (§5), reducers (try, filters), `cases.ts` loader incl. `C-LOADING` (deferred shard promise) and `C-SHARD-ERROR` (rejected shard load), `X-ERROR`, i18n parity, label coverage, contrast, `validate_data.mjs`, `csp.mjs` | every UI PR (`ui-unit`) |
| Playwright `populated-*`, `empty-*` (Chromium 360 + 1280) | full §14.2 matrix except Try it: assertions + axe + reflow + CSP | every UI PR (job `playwright`, part of required `ui / check`) |
| Playwright `populated-basepath-1280` | `basePath` smoke at `/pruefstand/` (§14.2): runtime URLs (shards, report link, theme script), site-root 404 | every UI PR (job `basepath-smoke`, part of required `ui / check`; N5.5) |
| Visual `toHaveScreenshot` | full §14.2 matrix, Chromium projects, `maxDiffPixelRatio: 0.01`, masks for times/latency/answer text; baselines only from the pinned Playwright container | nightly; informational until M7 |
| WebKit + mobile projects | full matrix: assertions + axe | nightly |
| Lighthouse CI | runs list, FAIL summary, cases list of the `D-MANY` 1,500-case run (populated set) | nightly; informational until M7 |
| Try-it matrix | Try-it rows × 8 combinations, real demo stack on the VM, sequential, reset before each combination (§14.2 Try-it run) | nightly job `demo-e2e` of the private `demo-nightly.yml` on the VM, after `demo-deploy` (T8.4 spec, T8.5 workflow; D244); informational, never a PR check, no `ui.yml` job |
| Post-deploy smoke (T8.5) | read-only Playwright on `https://dheena18.github.io/pruefstand/` (`basePath` `/pruefstand`; the docs at `/pruefstand/docs/` still load). **Step 0 (P5.5, UI13-05):** poll `/pruefstand/build-id.txt?nocache=…` until it equals `<workflow_run.head_sha>-<workflow_run.id>` (≤ 10 min, else fail "Pages still serves an older build"); every later request carries a cache-busting query. Then: `/` → `/de/`, runs list (`de` + `en`), first gated case-published run summary, its cases list, licences, its `report.html` (no such run in the index → runs list / `L-EMPTY` asserted and the run checks skipped with an annotation, UI13-17), an unknown path → 404 page with the docs link, footer attribution, axe, no CSP violation, exactly one CSP meta and no CSP header. Placeholder deploy → only `/` and `/docs/` (UI13-09) | job `post-deploy-smoke` of `docs.yml`, after each Pages deploy (N5.2) |

There is no preview deploy (GitHub Pages has none). Every UI PR builds both sets and runs the
Playwright matrix against them locally in CI (`playwright` job, empty `basePath`), and builds the
populated set once more with `basePath` `/pruefstand` for the `basepath-smoke` job, so `basePath` bugs
in runtime URLs fail the PR instead of the deploy (N5.5).

Extra specs: `keyboard.spec.ts` (skip link, theme + locale toggles, mobile sheet focus trap, sort
buttons, focus not obscured), `reflow.spec.ts` (§9), `content.spec.ts` (no `CANARY-` or raw chunk
text; `lang` rules of §9 incl. one `en` case; footer attribution on every page incl. root redirect and
404), `filters.spec.ts` (URL state survives reload and back), `locale.spec.ts` (`/` → `/de/`; switch
keeps path + query; `hreflang` alternates).

`docs/engineering/testing-strategy.md` §3.10 must equal §14.2–§14.3 (projects, sets, network rules,
layers; unknown run → `out/404.html` from `app/not-found.tsx`; Try it delays only through
`e2e/delay.ts`; UI11-15). Until it is rewritten, this section wins (UI-15, UI9-17). T8.1 rewrites §3.10 as a short
pointer plus this table, and T8.3 refreshes it, incl. the `basepath-smoke` layer row and the Try-it
row's in-container reset before each of the 8 combinations (UI13-18).

---

## 15. Data mapping: page → field → source

| Page / component | Displayed | Field | Source |
| --- | --- | --- | --- |
| Runs list | columns, flags | `RunIndexEntry`: `run_id, created_at, git_ref, git_sha, pr_number, n_cases, duration_s, cost_usd, complete, stop_reason, stack, workload, block, judged_subset, judge_mode, judge_fallback, judge_degraded, judge_drift, status, no_baseline, baseline_run_id` | `runs/index.json` (`DashboardRunIndex`) |
| Summary | status, blocking count | `status`, `no_baseline`; count of `hard_fails` + FAIL rows of the Gated table (§11.1) | `gate.json` |
| Summary | likely cause | `likely_cause` + `labels.causes` / `cause.<code>` | `gate.json` + `labels.json` |
| Summary | refs, splits, tier | `git_ref, git_sha, pr_number, splits, stack` (cand + base) | `run.json` |
| Summary / PR / HTML | workload, block, judged subset (UI13-19) | `workload`, `block` (`block <k>`), `judged_subset` (block-J caption "judged subset (150 cases)") | `run.json` (runs list: `RunIndexEntry`) |
| Summary | tokens, GPU-s, judge | `cost.prompt_tokens + cost.completion_tokens`, `cost.gpu_seconds` (tier 2), `judge_models`, `judge_mode`, `judge_fallback`, `judge_degraded`, `judge_drift`, `judged_cases` | `run.json` |
| Summary | baseline link / missing banner | `baseline_run_id` (null with `no_baseline`) vs index | `gate.json` + `runs/index.json` |
| Summary | hard fails | `hard_fails[].rule, case_id, metric, evidence` | `gate.json` |
| Summary / Diff | Base, PR, Δ, CI, MDE, status | `decisions[].baseline_mean, candidate_mean, result.*, mde, status` | `gate.json` |
| Summary / Diff / PR / HTML | δ | `decisions[].max_drop` | `gate.json` (W5.2) |
| Summary / PR / HTML | absolute value, max | `absolute_checks[].candidate_mean, max_value` | `gate.json` (W5.2) |
| Summary | table membership | `informational_reason`, `gated`, list membership, `stack` (§11.1) | `gate.json`, `run.json` |
| Summary | notable line | `notable_slices[]` with `notable == true` | `gate.json` |
| Summary / Diff | insufficient (n clusters) | `decisions[].n_clusters` where `status == INSUFFICIENT_DATA` (UI9-11) | `gate.json` |
| Summary / PR | informational rows + reason | block I rows + `labels.informational_reasons` / `info_reason.<code>` | `gate.json`, `labels.json` |
| Summary / PR | judged rows | block J rows; `judged_cases`, `judge_mode` | `gate.json`, `run.json` |
| Summary / PR | not applicable | `not_applicable_counts` | `gate.json` |
| Summary / PR | no-baseline notice | `no_baseline`, `eval_fingerprint` | `gate.json` |
| Summary | top failing cases | `top_failing_cases` | `gate.json` |
| Summary | HTML report link | `status != null` and case-published run (report exists exactly then, §2.3) | `runs/index.json` + `cases/<id>/0.json` presence (build time) |
| Summary | incomplete reason | `complete`, `stop_reason`, `infra_error` (only whether it is set; its value is never shown, UI12-16; published as the kind only, UI13-13) | `run.json` |
| Run sub-nav | cases published (`S-CASES-PRUNED`) | presence of `cases/<id>/0.json` (newest 20, N5.1) | build time |
| Run sub-nav | failing count | `failing == true` rows of shard 0 (build time) | `cases/<id>/0.json` |
| Slices | rows | `DashboardSliceRow`: `metric, dimension, value, status, gated, notable, kind, baseline_mean, candidate_mean, mean_diff, ci_low, ci_high, mde, max_drop, max_value, n_clusters, informational_reason` | `slices.json` (`DashboardSlices {schema_version, run_id, rows}`) |
| Cases list | rows, totals | `DashboardCase.case_id, tenant, lang, category, perturbation, question, failing`; total = sum of loaded shard lengths | `cases/<id>/<shard>.json` (`DashboardCases {schema_version, run_id, shard, n_shards, cases}`) |
| Case detail | question, answer, chunks | `question, answer, lang, retrieved_chunk_ids, retrieved_chunk_tenant_ids` | shard |
| Case detail | citations, metric values, per-metric status | `citations`, `metric_values`, `metric_status` | shard |
| Case detail | refused, error, expected refusal | `refused, error, expect_refusal` | shard |
| Case detail | baseline answer | same `case_id` in the baseline run's shards | baseline `cases/` |
| All | labels | `LabelsDocument.metrics, causes, hard_fail_rules, informational_reasons` (en; `hard_fail_rules` = code → label dict, D273) + `de.json` prefixes | `labels.json`, `de.json` |
| Footer / Licences | attribution | `licences.json` | `DATA_LICENSES.md` via `gen_licences.mjs` |
| Try it | answer, citations, chunks, refused, model | response body; `chunks[].used_in_prompt` | `POST /v1/query` |
| Try it | error kind, retry seconds | `code`, `retry_after_s` | error body (W5.5) |
| Try it | latency | client-measured elapsed time | browser |

---

## 16. Contract requirements (status)

All former requirements are now in interfaces.md §9 / §10 / §10.1. T1.9 and T8.1 implement them
verbatim. The fallback column applies only to data exported before they landed. `validate_data.mjs`
rejects such data unless its schema still allows the field to be absent.

| Id | Needed by | Contract (interfaces) | Fallback for old data |
| --- | --- | --- | --- |
| R1 | labels everywhere (UI-26, UI9-09) | `LabelsDocument` in `core.models.dashboard`; `labels_document() -> LabelsDocument` (T1.9); schema `schemas/labels.schema.json`; `data/labels.json` written by `export-dashboard` | raw codes shown in mono |
| R2 | slices Δ text | `DashboardSliceRow.mean_diff: float \| None` (copied from `result.mean_diff`) | no Δ text; bars + values only |
| R3 | leak badge on case chunks | `DashboardCase.retrieved_chunk_tenant_ids` (parallel to `retrieved_chunk_ids`) | no tenant badges; leak from the `tenant_leak` finding |
| R4 | shard order | cases sorted `failing` desc, then `case_id` asc; shard 0 holds every failing case | – (the build fails: failing count and static case pages need R4) |
| R5 | no-baseline (X5.5) | `GateReport.baseline_run_id: RunId \| None` (None iff `no_baseline`); `RunIndexEntry.no_baseline: bool` | – |
| R6 | typed slices (X5.3, UI9-04) | `DashboardSliceRow` (fields of §15) + `DashboardSlices {schema_version, run_id, rows}`; `kind` per §11.1 | – |
| R7 | one table rule (X5.4) | interfaces §9 table rule (Gated / Informational / Notable) and the invariant `informational_reason is not None ⇒ gated is False`; §11.1 here | – |
| R8 | Try-it chunk marker (X3.14) | `RetrievedChunk.used_in_prompt: bool \| None` (API v1, optional) | no marker |
| R9 | renderers without a baseline run (Y7.4, UI11-08, N6.1) | `render_pr_comment(report, base: RunManifest \| None, cand, *, report_url)`, `render_html(report, base: RunResults \| None, cand)`, `build_evidence_record(report, base: RunManifest \| None, cand, reviewer)` (interfaces §10) | – |
| R11 | infra-error status (D226, D264, D274, N6.1, P1.2, P4.2) | `GitHubPublisher.set_check(..., *, no_baseline: bool = False, infra_error: bool = False)` → commit state `error`, description `"executor infra error: <summary>"`, summary ending `; retrying once` or `; re-dispatch to retry` (interfaces §10 table; T1.9); `set_check` wraps the low-level `post_status(sha, state, description, context="pruefstand/gate")`, which the executor also uses for `pending` and "executor unhealthy" (P4.2) | – |
| R12 | en rule labels (UI12-15, D273) | `LabelsDocument.hard_fail_rules: dict[str, str]` (code → en label) | raw code in mono |
| R13 | block / judged subset in lists (UI13-19) | `RunIndexEntry.block: int \| None = None`, `RunIndexEntry.judged_subset: bool = False` (copied from `RunManifest`; interface change by T8.1) | Workload cell without `b<k>` / `subset` |
| R14 | shared size-cap constants (UI13-01, P5.1) | `MAX_INDEX_RUNS = 200`, `MAX_CASE_RUNS = 20` in `pruefstand.core.models.dashboard`, used by `export-dashboard` (T8.1), `push_dashboard_data` (T6.1) and `verify_dashboard_export.py` (T8.5) | – |
| R10 | demo server timeout (UI11-17) | `DEMO_TIMEOUT_S` default 75 < `NEXT_PUBLIC_DEMO_TIMEOUT_S` default 90 (interfaces §16) | – |
