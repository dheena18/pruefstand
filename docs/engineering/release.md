# Release

Decision: ADR-0017. Workflows: `ci-cd.md` §1 (`release-please.yml`, `release.yml`, `deploy.yml`, `dataset-release.yml`).

## 1. What is versioned

| Artefact | Version scheme | Breaking change means |
| --- | --- | --- |
| `pruefstand` package + CLI | SemVer `X.Y.Z` (`0.x` until M7) | removed/renamed CLI flag, changed exit code, removed public API in `interfaces.md` |
| Config (`pruefstand.yaml`) | `version: 1` field | a field removed or its meaning changed → `version: 2` + migration note |
| Run artefacts | `schema_version` in `run.json`, `gate.json` | a field removed or retyped |
| Target API | path `/v1` | any response field removed or retyped → `/v2` |
| GitHub Action | monorepo path `uses: dheena18/pruefstand/action@vX.Y.Z` (always); optional mirror repo `dheena18/pruefstand-action` with tags `vX.Y.Z` + moving `vX` and a Marketplace release (T9.1b, optional) | an input removed or renamed |
| Docker images | same as the package; digests in deployments | – |
| Dataset `pruefstand-de` | `vN` (released by `dataset-release.yml`, `workflow_dispatch` only); `eval_fingerprint` changes | any case added, removed or edited → new version |
| Metrics / prompts | per-metric `version`, prompt `_v<N>` files | definition change → new version (changes the fingerprint) |

## 2. Release steps (package, images, Action)

| # | Step | Who |
| --- | --- | --- |
| 1 | Merge feature PRs with Conventional Commit titles | sessions + you |
| 2 | release-please (token of GitHub App `pruefstand-release`, used by `release-please.yml` and the optional `sync-action-repo` job; environment `release`, one package, tags `vX.Y.Z`) updates the release PR (CHANGELOG, versions), then **runs `uv lock` (pinned uv) and commits the updated `uv.lock` to the release PR** (X2.9), so `uv sync --locked` stays green. The public `gate-router.yml` marks it `pruefstand/gate` = success "not gated (release version bump)" (with the `pruefstand-bot` App token, round 13 P1.1/P4.2) when its diff touches only version fields, `CHANGELOG.md` and the two workspace-member `version` lines in `uv.lock` (D105) | bot |
| 3 | Check the CHANGELOG, then make sure `main` is green, including the nightly | you |
| 4 | Merge the release PR → the release App creates tag `vX.Y.Z` (App-created tags trigger workflows; `GITHUB_TOKEN` tags would not) | you |
| 5 | `release.yml` `build-dist` → `publish-pypi` (Trusted Publishing, environment `pypi`); RCs go to TestPyPI via `workflow_dispatch` and a separate TestPyPI trusted publisher | CI |
| 6 | `release.yml`: build `pruefstand-action` and `rag-demo` images **on the tag** → push to GHCR by digest → cosign sign → SBOM (syft) + provenance → `cosign verify --certificate-identity .../release.yml@refs/tags/vX.Y.Z` (nothing is pre-built on the release PR); job `release-assets` attaches `image-digests.json` to the GitHub release (no expiry; the VM demo reads it anonymously, A12-M9) | CI |
| 7 | optional (T9.1b): `release.yml` `sync-action-repo` copies `action/` into `dheena18/pruefstand-action`, writes the digest built in step 6 into its `action.yml`, commits, tags `vX.Y.Z`, moves `vX`, creates a GitHub Release with "Publish to Marketplace" | CI (App token from environment `action-sync`, deployment tags `v*`) |
| 8 | Dashboard: the release commit's `push: main` run of `deploy.yml` (dashboard-only, UI13-06) builds `dashboard-site` (last 200 runs in the index, case shards for the last 20, N5.1); `docs.yml` runs via **`workflow_run`** on the successful `deploy.yml` (N5.2; no dispatch), downloads `dashboard-site` from `github.event.workflow_run.id`, fails above 800 MB, writes `build-id.txt` = `<head_sha>-<deploy_run_id>`, publishes dashboard (`/pruefstand/`) + docs (`/pruefstand/docs/`) to **GitHub Pages** (single Pages writer, Y7.1, D243) and runs the post-deploy smoke (it first waits until `build-id.txt` matches, max 10 min, P5.5). Demo (optional): `demo-ready.yml` (`workflow_run` of this release run): job `fetch-artefacts` (by run id, the one `actions: read` allowlist entry, P5.2; cosign verify), `pre-deploy-leak-probes` (T8.5, X2.8: leak probes against the demo candidate), `release-demo-ready` (`contents: write`, the second allowlist entry) uploads the release asset **`demo-ready.json`** only when no leak was found. The VM demo (Cloudflare Tunnel, Y7.5) is deployed by the next private nightly job `demo-deploy`: one anonymous `releases/latest` call, `demo-ready.json` + `image-digests.json` via `browser_download_url` (no artefact, no token, N5.3, P5.3), the **public GHCR image by digest**, then `demo-e2e` (D244). Every `main` push and a daily `deploy.yml` schedule refresh only the dashboard data | CI |
| 9 | Fresh-machine quickstart check (T9.2 job) on the released version | CI |

Per-job permissions only; within `release.yml`, `id-token: write` only on `publish-pypi`, `sign` and `attest`, `contents: write` only on `release-assets` (repo-wide allowlist: `ci-cd.md` §1; `deploy.yml` has no `id-token`, A12-M7). Trivy blocks on
HIGH/CRITICAL with a fix available (one policy everywhere, ignore file with reasons).

First-time setup (T9.1a, human): GitHub App for releases (contents write, tag creation); a **tag
ruleset** on `refs/tags/v*` (restrict creation, update, deletion; bypass = App `pruefstand-release`;
legacy tag protection is retired), checked by a rejected `git push origin v0.0.0-test`; PyPI and TestPyPI
trusted publishers for `dheena18/pruefstand` + `release.yml`; environment `release` with deployment
branch `main` only and **no** required reviewer (it runs on every push to `main`); environments `pypi`,
`huggingface` with you as required reviewer; environment `testpypi` with deployment branches **`main` only** (RC dispatches run from `main`; the TestPyPI trusted publisher matches repo + `release.yml` + environment, not the ref, so without the branch rule an agent branch with Workflows: write could publish under the project's TestPyPI name, A13-M2) (no `demo` or `preview` environment: Pages deploys with OIDC, the demo runs on the VM). Optional (T9.1b): environment `action-sync`
(deployment tags `v*`, holding the same release App key), and
create the public repo `dheena18/pruefstand-action` (root `action.yml`, no workflow files —
**verify** the current Marketplace requirements), install the release App there and accept the
Marketplace agreement.

## 3. Dataset release

| # | Step |
| --- | --- |
| 1 | `pruefstand build-dataset` produces `datasets/pruefstand-de/vN/` + `dataset_manifest.json` |
| 2 | `pruefstand validate dataset …` passes: schema, split sizes, cluster-aware splits, single license per config |
| 3 | Rotate the public canaries (retired ones → `canaries/retired.json`); `dataset-release.yml` `canary-check` fails if any held-out or retired canary is included (`security.md` DA1) |
| 4 | Update the dataset card (configs, licenses, attribution, review error rate, prompt versions) and `DATA_LICENSES.md` |
| 5 | Run `dataset-release.yml` (T9.1b, `workflow_dispatch`, input `version`) → exports to HF `<HF_USER>/pruefstand-de` (environment `huggingface`) |
| 6 | Re-baseline on `main` (new `eval_fingerprint`; `baseline-promote.yml` in the private executor picks up the next `main` commit; until then gated PRs get `failure` "no baseline for <fp>", so trigger it at once with `gh workflow run baseline-promote.yml -R dheena18/pruefstand-gate`) and record the dataset version in `docs/decisions.md`; also promote a `release` baseline for drift checks |

## 4. Release checklist

- [ ] `main` green, including the last nightly
- [ ] CHANGELOG reviewed; breaking changes have migration notes
- [ ] `schemas/` regenerated; dashboard types fresh
- [ ] Release images verified with `cosign verify` (exact identity); SBOM attached
- [ ] `action/action.yml` at the tag references `ghcr.io/dheena18/pruefstand-action:vX.Y.Z`; the digest in the release notes equals `image-digests.json` (and, if T9.1b is done, `pruefstand-action@vX.Y.Z` pins that digest)
- [ ] Marketplace listing shows the new version (only if T9.1b is done)
- [ ] Docs site updated by `docs.yml`; README results table matches `experiments/` outputs
- [ ] Dashboard on GitHub Pages smoke-tested; (optional) the next nightly `demo-deploy` deployed the demo-ready digest and `demo-e2e` passed; rollback target noted
