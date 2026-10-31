# 0017 — Release: release-please (App token), PyPI Trusted Publishing, cosign-signed GHCR images built on the tag, SBOM, optional Action repo

- Status: Accepted (revised 2026-10-28, round-1 R2.9–R2.10; round-2: images built on the tag, single package, Marketplace repo optional; revised 2026-10-31, round 8: tag ruleset, `release` environment without reviewer, docs deployed only by `docs.yml`, release PRs not gated; round 9: `uv lock` on the release PR (X2.9), `action-sync` environment, pre-deploy leak probes (X2.8); round 11 (D235, D239): dashboard on GitHub Pages through the single Pages writer `docs.yml`, Vercel dropped, optional demo on the VM, no `demo` environment)
- Date: 2026-10-27
- Tasks: T0.2, T9.1a, T9.1b

## Context
The release artefacts are the PyPI package, the Action image, the rag-demo image, the Marketplace
listing and the HF dataset (the GitHub Pages site, docs plus dashboard, is deployed by `docs.yml`). Tags or releases created with `GITHUB_TOKEN` do not start
other workflows. The Marketplace needs `action.yml` at the root of a repo with one action (and, per
current rules — **verify** in T9.1b — no workflow files).

## Decision
- Conventional Commits feed **release-please**, run with a **GitHub App token** (App `pruefstand-release`: contents + pull_requests write, used by `release-please.yml` and the optional `sync-action-repo` job, whose key copy lives in environment `action-sync` with deployment tags `v*`; the gate App is `pruefstand-bot`) (environment
  `release`: deployment branch `main` only and **no** required reviewer, because the workflow runs on every
  push to `main`; reviewers stay on `pypi`, `huggingface`), so its tag `vX.Y.Z` triggers `release.yml`. One release-please package for the repo
  (`include-component-in-tag: false`), so tags are plain `vX.Y.Z`. Versions follow SemVer and stay `0.x`
  until M7. There is no "digest before tag" commit on the release PR (release-please rewrites its branch).
  **`uv.lock` (X2.9):** the version bump changes the workspace members `pruefstand` and `rag-demo`, whose
  versions `uv.lock` records, so `release-please.yml` runs `uv lock` (pinned uv) after the bump and
  commits `uv.lock` to the release PR with the App token; otherwise `uv sync --locked` fails on every
  release PR. A release PR whose diff touches only version fields, `CHANGELOG.md` and those two
  `uv.lock` member `version` lines gets `pruefstand/gate` = success "not gated (release version bump)"
  from the public `gate-router.yml` (round 13 P4.2: "not gated" is posted only there, with the `pruefstand-bot`
  App token), so releases never wait for the A40s.
- `release.yml` (per-job permissions; `id-token: write` only on publish and sign jobs):
  1. builds sdist + wheel with `uv build` and publishes via **PyPI Trusted Publishing** (OIDC). Release
     candidates go to TestPyPI through a separate trusted publisher, started by `workflow_dispatch`; environment
     `testpypi` allows deployment branch `main` only, because the trusted publisher matches repo + workflow +
     environment but not the ref, and agent branches can carry workflow changes (A13-M2);
  2. builds `ghcr.io/dheena18/pruefstand-action` and `ghcr.io/dheena18/rag-demo` **on the tag**, pushes by digest,
     signs with **cosign keyless**, attaches an **SBOM** (syft, SPDX) and a build provenance
     attestation; Trivy blocks on HIGH/CRITICAL with a fix available;
  3. **optional (T9.1b, tier `optional`)**: syncs `action/` into the separate public repo
     **`dheena18/pruefstand-action`**, writing the just-built image digest into its `action.yml`,
     commits, tags `vX.Y.Z`, moves `vX` and publishes a GitHub Release with "Publish to Marketplace".
     Without it, users reference the Action from the monorepo: `uses: dheena18/pruefstand/action@vX.Y.Z`.
  `release.yml` does not deploy docs: `docs.yml` is the single GitHub Pages writer (two writers would
  overwrite each other). Since round 11 the Pages site also carries the dashboard (Y7.1): `docs.yml`
  assembles one artefact with the dashboard export at the site root `/pruefstand/` and the mkdocs site at
  `/pruefstand/docs/` (D243); the dashboard half is T8.5's `dashboard-site` artefact, downloaded from
  `github.event.workflow_run.id`: `docs.yml`'s deploy job is triggered by `workflow_run` on a successful
  `deploy.yml` (round 12 N5.2; no dispatch, no run-id search; the `pages` concurrency group sits on the
  deploy job only, N4.5).
- Verification instructions for users pin the identity exactly:
  `cosign verify --certificate-identity https://github.com/dheena18/pruefstand/.github/workflows/release.yml@refs/tags/vX.Y.Z --certificate-oidc-issuer https://token.actions.githubusercontent.com`.
- Tag protection: a tag ruleset on `refs/tags/v*` (restrict creation, update and deletion; bypass = App
  `pruefstand-release`), created in T9.1a; Done-when: a hand-pushed `v0.0.0-test` tag is rejected.
- `action/action.yml` at the tag references `ghcr.io/dheena18/pruefstand-action:vX.Y.Z` (a digest cannot
  be in the tagged commit); the digest is published in the release notes and in `image-digests.json`, which is also attached to the
  GitHub release as an asset (read by the VM demo, A12-M9).
- Dataset releases are separate (`dataset-release.yml`, `workflow_dispatch` only, environment `huggingface`, T9.1b).
- Deploy (`deploy.yml`, `workflow_run` of `release.yml`) downloads artefacts by the triggering run id
  and verifies their digests; it never uses "latest". Its job `pre-deploy-leak-probes` (T8.5, X2.8) runs
  the leak probes against the demo candidate (release image + `rag.public.yaml`); only a clean run marks
  the digest **demo-ready** (job `release-demo-ready` succeeds; no artefact). It builds the dashboard
  (`dashboard-site`, last 200 runs in the index, case shards for the last 20, N5.1); `docs.yml` then
  publishes exactly that artefact via `workflow_run` and fails above 800 MB. `deploy.yml` needs no
  `id-token` (A12-M7). The optional demo on the VM (ADR-0012) is deployed only by the private nightly job
  `demo-deploy`, which pulls the public GHCR image of the newest demo-ready release by digest (D244, N5.3).

## Alternatives considered
| Option | Why not |
| --- | --- |
| release-please with `GITHUB_TOKEN` | Its tags do not trigger `release.yml` |
| Marketplace listing from the monorepo | Marketplace needs a root `action.yml`, one action per repo; the monorepo path still works for `uses:` |
| Digest committed on the release PR before tagging | release-please force-rewrites its PR branch, and the commit triggers another build with a new digest |
| semantic-release | Node-centric, less transparent than a release PR |
| Dynamic package versions so `uv.lock` never changes | Possible, but adds build-backend config to two packages; one `uv lock` step is simpler (X2.9) |
| API tokens in secrets | Long-lived credentials |

## Consequences
- Positive: releases are reproducible, signed and auditable; no long-lived publish secrets.
- Negative: a release GitHub App to maintain (and, if T9.1b is done, a second public repo); Conventional Commits enforced by commitlint.
