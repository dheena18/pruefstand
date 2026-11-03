# Sequences

Trust model (ADR-0005): the public repo `dheena18/pruefstand` has **no self-hosted runner and no
secret that reaches the executor**. The persistent executor runner (on the TrueNAS VM `pruefstand-exec`;
running as the system user `pruefstand`; GPU models are served by one Ollama server for both A40s (ADR-0018), reached
through the `pruefstand-tunnel.service` tunnel, rounds 10 and 11) is
registered only to the private
executor repo `dheena18/pruefstand-gate`, which runs its own workflows from its own `main` and
**pulls** work: PR gates start only from the owner's `workflow_dispatch` of `gate-executor.yml` (round 13
P1.2), `baseline-promote.yml` polls `main`, nightlies run by schedule. Public workflow names: `ci.yml`, `ui.yml`, `docs.yml`,
`security.yml`, `live-e2e.yml`, `cassettes.yml`, `action-selftest.yml`, `build-images.yml`,
`gate-router.yml` (the only `pull_request_target` workflow, no checkout, posts with the `pruefstand-bot` App token from
environment `gate-router`, X2.2, P1.1), `executor-health.yml`,
`release-please.yml`, `release.yml`, `dataset-release.yml`, `deploy.yml`.
Private: `gate-executor.yml`, `nightly.yml`, `baseline-promote.yml`, `backup.yml`. Sanitised data
goes to the public repo `dheena18/pruefstand-dashboard-data` (`main`), the heartbeat to its branch
`heartbeat`.

Mermaid rule for this file: no `;` in any message or label (it ends a statement), see
`README.md` "Diagram conventions".

## 1a. Tier-1 live gate on a hosted runner (every PR)

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer
    participant Pub as Public repo (GitHub)
    participant Run as Hosted runner (live-e2e.yml)
    participant Cache as actions/cache
    participant Stack as compose live (Qdrant, rag-demo, llama.cpp, CPU embeddings)
    participant GHM as GitHub Models (informational judge)
    participant Art as Artefacts (live-baseline, live-baseline-nightly)

    Dev->>Pub: push branch / open PR
    Pub->>Run: live-e2e.yml (contents read, models read, actions read, comment job: pull-requests write for same-repo PRs only)
    Run->>Cache: restore model files (by SHA-256), slice index, judge cache (restore only on PRs)
    Run->>Stack: docker compose --profile live up (rag-demo built from this SHA)
    Run->>Stack: pruefstand run --config examples/live/pruefstand.yaml --tier pr, split smoke_live (20 cases, POST /v1/query)
    alt same-repo PR or main, quota left
        Run->>GHM: at most 10 judge calls (cache misses only, canary cases excluded, PRUEFSTAND_GH_MODELS_TOKEN from github.token)
        alt HTTP 429
            Run->>Run: judged metrics skipped, judge_mode=skipped
        end
    else fork PR (no models permission)
        Run->>Run: judged metrics skipped, judge_mode=skipped
    end
    Run->>Art: download latest live-baseline (push-to-main runs only, by run id), informational deltas only
    Run->>Run: pruefstand gate, decides on hard fails and error_rate only, language, citation, refusal and injection reported (paired stats INSUFFICIENT_DATA at n=20)
    opt nightly or PR touching apps/rag-demo/**
        Run->>Stack: scenario matrix, one job per bug switch (post_topk and unfiltered merge to hard FAIL, good to PASS)
    end
    alt same-repo PR
        Run->>Pub: upsert real PR comment, check live-e2e / gate
    else fork PR
        Run->>Pub: job summary only, check live-e2e / gate
    end
    opt push to main
        Run->>Art: upload live-baseline (20-case smoke_live, the only PR comparison)
    end
    opt nightly
        Run->>Art: upload live-baseline-nightly (40-case run, never used by PRs)
    end
```

No fakes: every answer comes from the real rag-demo and a real llama.cpp model (ADR-0008). The
required check never depends on a judge: judged metrics are informational and skipped when the quota
is gone or the PR comes from a fork. Only public data (5-law slice, public fixtures) is sent to GitHub
Models (ADR-0009).

## 1. PR gate (owner dispatches the private executor)

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer or coding agent
    actor Owner as Owner (browser or GitHub mobile app)
    participant Pub as Public repo (GitHub)
    participant Hosted as Hosted runner
    participant Router as gate-router.yml (hosted, pull_request_target, no checkout, environment gate-router)
    participant GHCR as GHCR (public package)
    participant Priv as Private repo pruefstand-gate
    participant Exec as Executor runner (VM pruefstand-exec)
    participant RAG as candidate rag-demo (VM, no GPU, no egress)
    participant Oll as Ollama (cluster, one server via the tunnel: generator + bge-m3, judge gemma3:12b)
    participant App as pruefstand-bot App
    participant DD as pruefstand-dashboard-data

    Dev->>Pub: push branch, open PR
    Pub->>Hosted: ci, ui, docs, security (tier 0, no secrets)
    Pub->>Hosted: live-e2e, action-selftest (tier 1, real CPU stack, deterministic gate, see 1a)
    Pub->>Router: pull_request_target event (opened, synchronize, reopened)
    Router->>Pub: read changed files and patches via API (pull-requests read)
    alt no gated path changed, or release-exempt lines only
        Router->>App: mint App token, status pruefstand/gate = success "not gated" on the head SHA
    else gated path changed
        Router->>App: mint App token, status pruefstand/gate = pending "gated: awaiting tier-2 dispatch"
    end
    Note over Pub,App: the ruleset pins pruefstand/gate to the pruefstand-bot App, a status posted with GITHUB_TOKEN does not count
    Pub->>Hosted: build-images.yml (no secrets, checks out the PR head SHA)
    Hosted->>GHCR: push rag-demo:sha-HEADSHA by digest, cosign sign (keyless)
    Hosted->>Pub: status pruefstand/image (digest) on the head SHA
    Owner->>Priv: workflow_dispatch gate-executor.yml with pr = N (the only tier-2 trigger, the VM token cannot reach this repo)
    Priv->>Exec: gate-executor.yml from private main (own concurrency group per PR)
    Exec->>Exec: MAINTENANCE check, file /var/lib/pruefstand/MAINTENANCE (present: pending "executor in maintenance, re-dispatch later", stop)
    Exec->>Pub: read PR N, changed files, head SHA at dispatch time, pruefstand/image status (App token, read)
    alt no gated path changed
        Exec->>Exec: end (gate-router.yml owns the status)
    else head SHA has no pruefstand/image status yet
        Exec->>App: post_status pending "image not built yet, re-dispatch after build-images"
    else gated
        Exec->>Exec: flock /var/lib/pruefstand/gpu.lock once (wait up to 2 h, heartbeat every 15 min, timeout gives pending "executor busy, re-dispatch")
        Exec->>Oll: preflight under the lock: health.sh --repair (tunnel, start-ollama.sh over SSH with setsid nohup only if no server runs, day-mode models resident with catalogue digests)
        Exec->>Exec: data root writable with at least 20 GB free (else error, infra_error data_root_unavailable), df, GPU memory via status.sh, failure gives error "executor unhealthy"
        Exec->>Exec: load pruefstand.yaml, dataset, judge config, pruefstand package from public main (never from the PR)
        Exec->>Pub: read PR rag.gpu.yaml + image digest from status pruefstand/image
        Exec->>GHCR: anonymous pull by digest, cosign verify (origin only)
        Exec->>Priv: read baselines/index.json (branch baselines), then baseline files from the data root /mnt/pruefstand/baselines (sha256 checked)
        alt no baseline for eval_fingerprint
            Exec->>App: status pruefstand/gate = failure "no baseline for FP, run baseline-promote"
            Exec->>Priv: append (pr, head sha, dispatch run id, failure) to state/processed.jsonl
        else baseline found
            Exec->>Exec: start Qdrant and rerank-cpu on gate-net, llm-proxy on gate-net + proxy-egress (llm-proxy:11500, D242), swap the generator if the PR selects another catalogue model, and a PR-scoped collection if embedding/chunking changed
            Exec->>RAG: start candidate on internal network gate-net (no GPU, no egress, read-only fs, no canary registry)
            Exec->>RAG: GET /v1/info (models + serving + corpus_version to target_fingerprint)
            Exec->>RAG: pruefstand run --tier pr (smoke + core via /v1/query, robust_pr via /v1/retrieve only, at most 90 min, --judged-subset limits generation and judging of core answerable cases only if the fallback is on)
            RAG->>Oll: generation + bge-m3 embeddings via llm-proxy (generator + embed tags only, native API, num_ctx and keep_alive enforced, sampling options within catalogue bounds)
            Exec->>Oll: judged metrics with the judge on the judge card (pipelined with generation)
            Exec->>Exec: pruefstand gate --from-store --ref main (one Holm family over all testable gated pairs)
            Exec->>Exec: keep the full run dir on the VM disk, upload run.json, gate.json, comment.md (14 days)
            alt infra failure during the run (Ollama down, tunnel lost, data root unavailable, model reload)
                Exec->>Exec: stop_reason aborted with infra_error, health.sh --repair, one automatic retry
                Exec->>App: status pruefstand/gate = error "executor infra error: SUMMARY, retrying once" (never failure, not recorded)
                opt the retry also hits an infra failure
                    Exec->>App: status pruefstand/gate = error "executor infra error: SUMMARY, re-dispatch to retry"
                    Exec->>Priv: append (pr, head sha, dispatch run id, error) to state/processed.jsonl
                end
            else run completed
                Exec->>App: redacted comment + status pruefstand/gate (set_check)
                App->>Pub: upsert PR comment, set status
                Exec->>Priv: append (pr, head sha, dispatch run id, result) to state/processed.jsonl
            end
        end
        Exec->>Exec: stop candidate, drop PR collection + PR cache overlay (job_completed hook)
    end
    Exec->>DD: force-push heartbeat.json to branch heartbeat (every 15 min while a job runs or waits)
```

The executor never runs workflow files, scripts or gate config from the PR. From the PR it uses only
`apps/rag-demo/configs/rag.gpu.yaml` (X3.15) and the candidate image; the candidate is untrusted (the image signature proves origin, not
content) and runs without GPU or internet; it reaches Ollama only through `llm-proxy` (generator + embed tags only, no admin
API, native endpoints only) and never a judge model (allow-list, ADR-0018). An infra failure during a run gives `error`
and one retry, never `failure` (Y5.2); after a second infra failure the job is recorded with result
`error` and runs again only after a new owner dispatch (A12-M1, P1.2). Public PRs get a redacted comment: no chunk text, canaries
masked, plus δ and the MDE for each gated metric. A new push needs a new dispatch, and a gated
PR without a baseline never passes. Only the owner can dispatch (browser or GitHub mobile app); the VM
token of the coding agents can push branches, open PRs and push workflow files, but cannot reach the
private repo and cannot produce the App-pinned `pruefstand/gate` (P1.3).

## 2. Fork PR

```mermaid
sequenceDiagram
    autonumber
    actor Ext as External contributor
    participant Pub as Public repo (GitHub)
    participant Hosted as Hosted runner
    actor Maint as Owner
    participant Priv as Private repo pruefstand-gate
    participant Exec as Private executor

    Ext->>Pub: open PR from fork
    Pub->>Hosted: ci, ui, docs, security, live-e2e on pull_request (read-only token, no secrets, judge skipped)
    Hosted-->>Pub: checks (build-images builds but cannot push from a fork)
    Note over Pub,Hosted: no self-hosted runner on this repo, only gate-router.yml uses pull_request_target (no checkout)
    Maint->>Pub: review the diff
    opt worth a GPU run
        Maint->>Pub: scripts/mirror_fork_pr.sh N pushes the reviewed head to gate/pr-N (no PR is opened)
        Note over Maint,Pub: script refuses diffs touching .github/, infra/runner/, infra/gate-executor/, action/, itself
        Pub->>Hosted: build-images.yml on gate/pr-N gives image + status pruefstand/image
        Maint->>Priv: workflow_dispatch gate-executor.yml with pr = N (browser or mobile app)
        Priv->>Exec: gate-executor.yml from private main
        Exec->>Pub: read the fork PR head SHA at dispatch time
        alt gate/pr-N head SHA equals the fork head SHA
            Exec->>Pub: gate gate/pr-N (flow 1), post comment + status on that SHA only
        else SHAs differ (fork pushed after mirroring, or gate/pr-N changed by someone else)
            Exec->>Pub: no gate run, pending "fork head moved since mirroring, re-mirror and re-dispatch" on the current head
        end
    end
```

Fork PRs follow the same rule as any PR (the candidate is untrusted either way). The result is posted
only on the SHA the owner reviewed, mirrored and dispatched (X2.3, P1.2), so a later fork push never
inherits a green `pruefstand/gate`. The `gate/pr-N`
branch exists only because a fork's `pull_request` run cannot push an image to GHCR; there is never a
mirror PR, so the fork's code never runs with same-repo permissions.

## 3. Merge to main: baseline promotion

```mermaid
sequenceDiagram
    autonumber
    participant Pub as Public repo
    participant Priv as Private repo pruefstand-gate
    participant Exec as Executor runner (VM pruefstand-exec)
    participant RAG as rag-demo (main image)
    participant Disk as Data root PRUEFSTAND_DATA_ROOT/baselines (VM disk)
    participant Base as Private branch baselines (index.json only)
    participant DD as pruefstand-dashboard-data

    loop every 15 min (schedule) or workflow_dispatch
        Priv->>Exec: baseline-promote.yml (private main, own concurrency group)
        Exec->>Pub: new main head commit since last promotion?
        Exec->>Exec: newest complete, unpromoted nightly run in the VM run storage?
    end
    Exec->>Exec: flock gpu.lock once, then preflight
    Exec->>RAG: anonymous pull of the main image by digest, cosign verify, start (no GPU, no egress)
    Exec->>RAG: pruefstand run --tier pr
    Exec->>Exec: require complete=true, no hard fails, error_rate <= 0.02
    Exec->>Disk: pruefstand baseline promote --run RUN_ID --ref main (also the nightly run under its own fingerprint)
    Exec->>Disk: write history/RUN_ID.partial, then rename, baselines/EVAL_FP/main/ + manifest.json (sha256 per file), keep the last 20
    Exec->>Base: commit index.json (per fp and ref: ordered run ids + manifest sha256), GITHUB_TOKEN
    opt first poll after 00:00 UTC on day 1 of the month
        Exec->>Disk: baseline-prune (retention, data-model 7)
    end
    Exec->>DD: push sanitised run.json, gate.json, runs/index.json + manifest.json (repo-scoped PAT)
    Exec->>DD: force-push heartbeat.json to branch heartbeat
```

Only this private workflow writes baselines (including the monthly prune). Baseline files live in the
data root on the VM disk (single writer, write-then-rename) and in the encrypted weekly backup; the private repo's `baselines` branch holds only a
small `index.json` (X2.7), so the repo no longer grows with every promotion. Baselines are plain files
(no signatures): write access to the VM runner user, the data root and the private repo is the trust boundary,
and the sha256 manifest is checked on every read. Nightly runs are promoted by this poll, never by a dispatch from
`nightly.yml`, so a pending run can never be dropped. A block-*k* nightly is promoted to ref `nightly-b<k>`
(round 12 N1.4). The release anchor is per block (AI13-09, A13-M5, D321): the **release run of all of `full`** (the newest
`v*` tag's image, no `--block`, alone on its night, never gated; repeated each night until the refs exist for
the current fingerprint) is promoted by this poll three times, as `release-b0`, `release-b1`, `release-b2`
(each the block-*k* projection under the block-*k* fingerprint). Runs with `judge_fallback`, `judge_drift`,
`judge_degraded`, a judged metric informational for `judge_truncated` or `infra_error` are never promoted
(AI13-08, D321).

## 4. Nightly run and drift check

```mermaid
sequenceDiagram
    autonumber
    participant Cron as schedule 20:07 and 21:07 UTC, hosted guard by the cron that fired (22:07 local)
    participant Exec as Executor runner (VM pruefstand-exec)
    participant RAG as rag-demo (main, rag.gpu.yaml, generator on Ollama, generator lane)
    participant Big as judge gemma3:12b (same as PR, ADR-0019, Ollama, judge lane)
    participant Base as Baseline store (data-root files + index.json)
    participant Pub as Public repo
    participant DD as pruefstand-dashboard-data

    Cron->>Exec: nightly.yml (private, own concurrency group), hosted job guard sets run = true only for the cron of the current Berlin offset, plus the fired night's deadline
    alt guard output run = false
        Exec->>Exec: nightly job skipped by its if condition (no second nightly per night)
    else job starts at or after 06:00 Berlin of the fired night
        Exec->>DD: heartbeat last_nightly_status = "aborted: window_exceeded", infra_error window_exceeded, reported once for that night
    else MAINTENANCE file present or lock not obtained before 06:00
        Exec->>Pub: commit status pruefstand/nightly = success "skipped: maintenance" (maintenance case)
        Exec->>DD: heartbeat last_nightly_status = "skipped: REASON" (last_nightly_at unchanged), executor-health opens issue "nightly skipped"
    else normal night (one orchestrator job, deadline 06:00 Berlin checked before every phase)
        Exec->>Exec: flock /var/lib/pruefstand/gpu.lock once (until the deadline), export PRUEFSTAND_LOCK_HELD=1, heartbeat every 15 min
        Exec->>Exec: preflight under the lock (health.sh --repair incl. data root check, df, GPU memory)
        Exec->>Exec: switch-mode.sh night (no new lock: same models as day, nothing swapped, ADR-0019)
        Exec->>Big: judge-drift first: 50 anchors (a judge that drifted tonight never gates tonight)
        Exec->>Exec: read state/nightly_counter, k = counter mod 3
        par generation (generator card)
            Exec->>RAG: pruefstand run --split full --stratum all --block auto (refusal stratum + block k, at most 600 cases), responses into target cache
        and judging on the judge card (overlapping)
            Exec->>Big: judged metrics on cached responses as they arrive (judge cache hits skip unchanged cases)
        end
        Exec->>Base: BaselineStore.get(eval_fingerprint, nightly-b(k))
        Exec->>Exec: pruefstand gate --ref nightly-b(k), the latest promoted main nightly of the same block
        Exec->>Exec: gate phase complete, so counter + 1 on branch executor-state
        opt release night (release-b0..b2 of the newest tag missing for this fingerprint, D321)
            Exec->>RAG: run the newest tag image on all of full instead of the block run (never gated, promoted later as release-b0..b2, no drift tonight)
        end
        Exec->>Base: BaselineStore.get(eval_fingerprint, release-b(k))
        Exec->>Exec: drift gate block k vs release-b(k), or report drift no release baseline once
        Exec->>Exec: contamination probe, cause-switches (Sundays only, judge_mode skipped except the refusal row with --stratum refusal)
        Exec->>Exec: switch-mode.sh day (no new lock, restores the day set if a phase changed it), also in finally
        Exec->>Exec: runs and cache prune, repo-size guard
        opt a phase does not fit before 06:00
            Exec->>Exec: stop: stop_reason aborted, infra_error "window_exceeded: PHASE", no retry, nothing promoted
        end
        Exec->>Pub: commit status pruefstand/nightly = success, failure or error on the main SHA (always, non-blocking, D91)
        Exec->>DD: push sanitised artefacts, force-push heartbeat.json (last_nightly_at, last_nightly_status ok or failed) to branch heartbeat
    end
    opt optional demo exists
        Exec->>Exec: after 06:00, demo-nightly.yml (same guard output and if): demo-deploy (one releases/latest API call, image-digests.json via browser_download_url, public GHCR image by digest, cosign verify), then demo-e2e (sequential)
    end
```

The nightly tier runs `pruefstand run --split full --stratum all --block auto`: the refusal stratum (`block=None`,
≈ 150 unanswerable cases, at least 100 clusters) plus block *k* (`state/nightly_counter` mod 3, the counter
advanced only after a completed nightly, P4.4), at most 600 cases, so `full` is covered every 3 completed
nightlies (SPEC §6.2, Y4.3, round 12 N1); it gates against baseline ref `nightly-b<k>` and checks drift against
the release anchor `release-b<k>` (N1.4, AI13-09),
with the same judge as the PR tier (`gemma3:12b` on the judge card, ADR-0019;
generation on the generator card and judging on the judge card overlap;
any other judge sets `judge_fallback=true`, which makes judged metrics informational,
Y4.4), so it has its own `eval_fingerprint` and baseline line. Comparing against
the last release baseline catches slow drift that per-merge baselines hide. The status is posted every
night, so a missing nightly is visible; a night that cannot start or is stopped at the deadline is
written to the heartbeat and opens the `nightly skipped` issue (N4.3). Budget: one orchestrator job,
≤ 8 h, hard deadline 06:00 Europe/Berlin of the fired night, checked at start and before each phase
(`ci-cd.md` §1.2); the guard's `run` output and the job's `if:` stop the off-season cron from starting a
second nightly (P2.1). The
switch-mode calls run inside the orchestrator's lock with `PRUEFSTAND_LOCK_HELD=1` and never re-take
it (X2.1). The CPU-only simulation, Hypothesis and mutmut jobs run in the public `ci.yml` nightly
schedule, not here.

## 5. Dataset build

```mermaid
sequenceDiagram
    autonumber
    actor O as Owner (50-item spot-check)
    participant CLI as pruefstand build-dataset
    participant Gen as Datagen LLM (public text: GitHub Models free tier, family not qwen or gemma, private docs: local judge model, ADR-0019)
    participant RM as Review model (local judge gemma3:12b, batch job, reject-only)
    participant Sup as Support check (LLMClient + support_check_de_v1)
    participant Rev as Review tool (tools/review_app)
    participant HF as Hugging Face

    CLI->>Gen: generate_qa(chunks, prompt_version)
    Gen-->>CLI: QACandidates
    CLI->>Sup: check_support(candidate, chunk, llm, model)
    CLI->>CLI: check_overlap, dedupe, perturb_case(_async), attack cases from pipeline, refusal cases
    CLI->>CLI: assign_splits (cluster_id-aware, incl. SMOKE_LIVE and ROBUST_PR), validate_dataset
    CLI->>RM: review 100 % of smoke and core, seeded 20 % sample of full
    RM-->>CLI: ok / bad per item (deterministic checks override, the judge never writes or rewrites references)
    CLI->>Rev: 50-item spot-check with side-by-side source §
    O->>Rev: citation correct? answer plausible?
    Rev-->>CLI: ReviewRound (sampled, bad, error_rate = model review)
    alt error rate > 10 %
        CLI->>CLI: new prompt version, regenerate
    else
        CLI->>CLI: closed-book run, tag closed_book_answerable
        CLI->>HF: dataset-release.yml: export_hf per licence config (dir/hf_export/, public canaries rotated)
    end
```

Every generated row carries `generation_prompt_version`, so a rejected batch can be traced to one
prompt file. The gating split `core` gets a full model review (D124). Publishing is a separate step
after review, with one config per licence (ODbL never mixed with another share-alike licence; MEMERAG
never exported), and held-out canaries are never exported.

## 6. Judge calibration (RQ2)

```mermaid
sequenceDiagram
    autonumber
    participant BCS as build_calibration_sets (T5.3)
    participant Src as MEMERAG-DE / GermanQuAD / GermanRAG
    participant Exp as experiments/rq2
    participant J as Judges (A40 gemma3:12b, gemma3:4b size contrast pulled one at a time, GitHub Models non-qwen)
    participant Cal as judges.calibration

    BCS->>Src: download (MEMERAG download-only, never redistributed)
    BCS-->>Exp: datasets/calibration/v1 (labels by expert vote or by construction, incl. hard negatives)
    opt T5.3-opt (only if a German annotator is available)
        Exp->>Exp: add 100 human labels as a check
    end
    loop each judge
        Exp->>J: Judge.score on every pair
        J-->>Exp: verdicts + cost from llm_calls
    end
    Exp->>Cal: calibration_table(labels, verdicts)
    Cal-->>Exp: binary kappa with 95 % cluster-bootstrap CI on the full set, specificity on the hard-negative subset with Wilson bound, Spearman, cost, latency, bias
    alt some judge has kappa >= 0.6 on the full set and specificity >= 0.80 on hard negatives (Wilson lower bound >= 0.70)
        Exp->>Exp: pin the cheapest passing judge, store its 50 drift-anchor verdicts, update decision log
    else no judge passes
        Exp->>Exp: judged metrics informational only in every tier, follow-up opened
    end
```

Calibration is offline and scripted with a fixed seed. κ is never computed on a single-label subset
(X1.1); the in-domain `legal_hard` set is built in T5.3 (X3.1). Hard negatives (D119) are same-paragraph wrong
spans, number/date swaps, negation flips, partially correct answers and MEMERAG "Not Supported" items.
The chosen gating judge goes into config and the decision log, and changing a judge prompt version means
re-running this sequence.

## 7. Demo "Try it" query

```mermaid
sequenceDiagram
    autonumber
    actor V as Visitor
    participant D as Dashboard /de/try or /en/try (GitHub Pages)
    participant CF as Cloudflare Tunnel (outbound from the VM)
    participant API as Demo API (rag-demo on the VM, demo-net)
    participant RL as Rate limiter + budget guard
    participant LLM as llama.cpp generator (VM CPU, demo-net)

    V->>D: pick tenant from fixed list, ask question
    D->>CF: POST /v1/query
    CF->>API: forward (CF-Connecting-IP)
    API->>RL: check in-process per-IP limit (10 req/min), daily limit and budget
    alt per-IP or daily limit exceeded
        RL-->>D: 429 JSON {code: rate_limited or daily_limit, message, retry_after_s}
    else daily budget spent or kill switch on
        RL-->>D: 503 JSON {code: budget_exhausted or demo_disabled, message, retry_after_s}
    else allowed
        API->>API: retrieve (tenant filter inside every prefetch and on the fused query, RRF)
        API->>LLM: generate answer
        LLM-->>API: answer
        API-->>D: answer + citations + chunks
        D-->>V: render with citations
    end
```

The public demo has no write paths and a fixed tenant list. A per-IP rate limit and a hard daily budget
(ADR-0012) are checked before any LLM call, and every error carries a JSON body, so the page never has
to read the `Retry-After` header (D138). The optional demo runs on the VM on its own Docker network
`demo-net` behind an outbound Cloudflare Tunnel (Y7.5), never on `gate-net` or the A40 cluster.

## 8. Runner: one case (T1.8)

```mermaid
sequenceDiagram
    autonumber
    participant R as Runner (semaphore = concurrency)
    participant C as target cache (namespace target)
    participant T as TargetAdapter
    participant M as deterministic metrics
    participant J as JudgeStage
    participant B as Budget
    R->>R: route: robust_pr (or core answerable outside --judged-subset) -> retrieve, else answer
    R->>C: get(stable_hash(target_fp, case.id, question, tenant)), a hit of the other mode is a miss
    alt cache hit
        C-->>R: response (cached=True, attempt=0)
    else miss
        loop at most max_retries + 1 tries
            R->>T: query / retrieve under asyncio.wait_for(timeout_s)
            alt TargetError(transient) or timeout
                R->>R: sleep backoff_s * 2^k * (1 + 0..25 % seeded jitter)
            else ok, or non-transient error
                T-->>R: response or error (error text <= 500 chars)
            end
        end
        opt retrieve answered None (404/405)
            R->>T: query instead (counts.retrieve_fallback, mode=answer)
        end
        R->>C: set(response) (never an error)
    end
    R->>M: evaluate_deterministic, synchronously (shared regex budget), failed request -> error values, error_rate = 1
    alt a hard-fail metric fired (canary_leak, tenant_leak, system_prompt_leak)
        R->>R: judged values not_applicable (hard_fail), no judge call
    else judged metric, judges given, case in scope
        R->>B: reserve(2), refused -> not_applicable judge_cap, counts.judge_skipped
        R->>J: await metric.acompute(case, resp, judges)
        J-->>R: value | LLMError / PolicyViolation -> error value, counts.judge_error | QuotaExhausted -> judge_quota for the rest of the run
        R->>B: release(2 - requests this call charged)
    end
    Note over R,B: BudgetExceeded (USD / tokens) cancels the pending cases: complete=False, stop_reason=budget_exceeded, finished cases kept. Cancellation / KeyboardInterrupt: stop_reason=aborted, infra_error unset
```

Results keep the input order. After the run, `judge_error / judged_cases > 5 %` sets `judge_degraded`. An
executor infra failure is a different path: the executor calls `ArtifactStore.mark_aborted(run, infra_error)`
(R11 D245) on a finished or partial run.

## 9. rag-demo: one retrieval (T3.5, `/v1/query` and `/v1/retrieve`)

```mermaid
sequenceDiagram
    autonumber
    participant C as Caller (runner or demo)
    participant A as rag-demo API
    participant R as QdrantRetriever
    participant M as CorpusMeta
    participant Q as Qdrant (alias chunks_active)
    participant K as rerank-cpu (VM CPU, no auth)

    C->>A: POST /v1/query or /v1/retrieve {tenant_id, question, top_k}
    A->>M: get() (cached 10 s)
    M->>Q: GET collection (api-key header)
    M-->>A: complete and same analyzer fingerprint, else 503 re-index
    A->>R: retrieve(tenant_id, question, top_k)
    R->>R: allowed_tenants, embed query (dense) and tokenise (sparse)
    R->>Q: ONE Query API call: prefetch dense and sparse, filter tenant_id in tenant and shared_public in EACH prefetch and on the fused query, RRF k=60
    Q-->>R: fused points (payload)
    opt reranker on, and /v1/query or rerank.on_retrieve true
        R->>K: POST /rerank, first 10 passages cut to 256 tokens, one batch, no Authorization
        K-->>R: scores
    end
    R->>R: cut to top_k, ranks 1..n, guard: foreign tenant raises TenantIsolationError
    R-->>A: hits
    A-->>C: /v1/query adds the generator answer, /v1/retrieve returns chunks only
```

The seeded bugs change only step 6 (`tenant_filter: post_topk` sends no filter and filters in Python after
the cut, `shared_public_merge: unfiltered` adds a second unfiltered query) and switch the guard off.
