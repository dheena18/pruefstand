# 0011 — Dashboard = Next.js static export over run artefacts

- Status: Accepted (revised 2026-10-31: round 8 W5; round 9 X1.2; round 11 D235-D237, D239: GitHub Pages, `_empty` param, derived fixtures, demo on the VM)
- Date: 2026-10-27
- Tasks: T8.1–T8.5

## Context
The dashboard is for browsing runs, diffs and failing cases. It must never compute metrics, because the
Python package is the single source of truth for them. It should also be cheap to host.

## Decision
- Next.js (App Router) with `output: "export"`, TypeScript `strict`, Tailwind and hand-written SVG charts (no chart library; amended by T8.2b, D664: owner-accepted on condition that every chart is accessible, see ui-spec §8).
- Data is static JSON. `pruefstand report --format json` (or an export script) writes it to `apps/dashboard/public/data/`,
  or the dashboard fetches it from a static URL.
- **Hosting: GitHub Pages** (free; D235). The build (data checkout, validation, CSP hashing) runs in
  GitHub Actions and Pages serves the prebuilt `out/`. GitHub Pages sets no custom headers, so the CSP
  is delivered only as a hash-based `<meta http-equiv="Content-Security-Policy">` per page; there are
  no header files (Vercel and its `vercel.json` are dropped). Directives that `<meta>` cannot carry
  (`frame-ancestors`) are not available; ui-spec §7.4 states the resulting policy. Layout (D243): the dashboard
  is the **site root** `https://dheena18.github.io/pruefstand/` (`basePath` `/pruefstand`), the docs live at
  `/pruefstand/docs/`; `docs.yml` (ADR-0017) is the single Pages writer and deploys one artefact, the dashboard
  half of which is built by T8.5's `deploy.yml` (artefact `dashboard-site`, downloaded by run id).
- TypeScript types are generated from `schemas/*.schema.json` with `json-schema-to-typescript`, and CI fails if they are stale.
  Data is **schema-validated at build time** (validators generated from the same schemas); invalid data
  fails the build in CI before deploy, so the static site has no "bad data" panel.
- UI source of truth: `docs/design/ui-spec.md` (pages, states, tokens, i18n with static de/en dictionaries and
  `/de` `/en` route prefixes, default `de`, licence footer on every page).
- Cases: a cases list page with a client-side filter over sharded `cases/<run_id>/<shard>.json`; individual case
  pages only for failing and top-N cases. `report.html` is exported next to the run data.
- UI tests: Vitest for components, Playwright for e2e, visual regression and mobile viewports, axe-core for accessibility,
  and Lighthouse CI. A static export pre-renders one data tree, so there is **one build per fixture set**:
  `apps/dashboard/fixtures/{populated,empty}/`, each built and tested as its own Playwright project. The `empty`
  set builds because `generateStaticParams` returns one placeholder param `_empty` with `dynamicParams = false`,
  which renders the empty state (D236). The fixtures F-PARTIAL, F-NO-BASELINE and F-JUDGE-SKIPPED are derived from
  real tier-1 runs by `scripts/dashboard/derive.py` (D237; path moved by D268). The error state is tested via the 404 page
  (`out/404.html` from `app/not-found.tsx`); loading states delay real responses only through `e2e/delay.ts`,
  never changing data (`testing-strategy.md` §3.10, ui-spec §14).
- The "Try it" page is the only dynamic part. It calls the optional demo API (ADR-0012), which runs on the VM
  behind a free Cloudflare Tunnel with a CPU model and in-process rate limits (D239); API errors are JSON
  `{code, message, retry_after_s}`.

## Alternatives considered
| Option | Why not |
| --- | --- |
| Streamlit/Gradio | Fine for internal tools (the labeling tool uses Streamlit), not for a public portfolio UI |
| Next.js SSR + API | Needs a server and a database, with no benefit for static data |
| Hand-written TS types | They drift away from the Pydantic models |
| Vercel (round 9 plan) | Headers need a Vercel-side build or `vercel.json` inside `out/`; free GitHub Pages is enough for a static site (D235) |

## Consequences
- Positive: hosting is free (GitHub Pages), there is no backend, and the types are contract-tested.
- Negative: no response headers on Pages; the CSP is `<meta>`-only, so `frame-ancestors` and `nosniff` cannot be set.
- Negative: new data needs a re-export and a redeploy. CD automates both.
