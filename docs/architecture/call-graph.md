# Call graph

How functions connect for each entry point. Names are the public names from `interfaces.md`;
private helpers are left out. The CLI is a package: `pruefstand/cli/__init__.py` holds the Typer
`app`, and each command lives in `cli/<command>.py`.

## 1. `pruefstand run`

```mermaid
flowchart TB
    cmd["cli/run.py: run --config --tier --out"] --> load["core.config: load PruefstandConfig"]
    load --> re["pipeline.run_eval(cfg, tier, out)"]
    re --> ds["load TestCase JSONL for cfg.splits<br/>(tier 2 PR: smoke + core + robust_pr, tier 1: smoke_live)"]
    re --> ba["adapters.build_adapter(cfg.target)<br/>type=http"]
    ba --> http["HttpTargetAdapter"]
    re --> info["TargetAdapter.info()"]
    info --> pre{{"corpus_version matches dataset?"}}
    pre ==>|"no"| cm["abort: CorpusMismatch<br/>stop_reason=aborted, exit 1"]
    pre -->|"yes"| fam{{"judge family != reported generator family?"}}
    fam ==>|"no"| ce["ConfigError: run aborted<br/>stop_reason=aborted, exit 2"]
    fam -->|"yes"| tfp["core.fingerprint.target_fingerprint(info, url=..., run_id=...)<br/>includes image digest/git SHA, config_hash, corpus_version, models, serving"]
    re --> mk["LLMClient(LiteLLMBackend, llm KVCache, Budget, CallRecorder)<br/>allowed_providers + external data guard<br/>tier 1: GitHub Models, at most 10 judged cases, informational<br/>429 or fork: judge_mode=skipped (no fallback judge)"]
    mk --> jp["JudgePool(Judge per cfg.judge.pr or nightly)"]
    re --> reg["MetricRegistry"]
    re --> rn["Runner(adapter, metrics, judges, target cache, budget, cfg.runner)"]
    tfp --> run["Runner.run(cases, target_fingerprint, seed, judged_subset)"]
    rn --> run

    run --> c1{{"target cache hit?<br/>main cache read-only + PR overlay"}}
    c1 -->|"miss"| q["TargetAdapter.query(TargetRequest)"]
    c1 -->|"hit"| rec["CaseRecord(cached=true)"]
    q -->|"ok"| rec
    q -->|"error after retries"| er["CaseRecord(error=...)<br/>worst value for every metric"]
    rec --> det["metrics.evaluate_deterministic(case, resp, metrics)<br/>+ LatencyMetric.from_record"]
    er --> sc
    det --> hf{{"hard-fail metric fired?<br/>canary_leak, tenant_leak, system_prompt_leak"}}
    hf ==>|"yes: skip judges for this case"| sc["ScoredCase"]
    hf -->|"no"| jm["JudgedMetric.acompute(case, resp, judges)"]
    jm --> js["Judge.score(JudgeTask)<br/>kontext = exactly the chunks the generator saw"]
    js -.->|"LLMError / PolicyViolation"| jerr["MetricValue(status=error, value=None)<br/>more than 5 % of cases: judge_degraded"]
    jerr --> sc
    js --> cj["LLMClient.complete_json(LLMRequest, schema)<br/>llm cache key lives here only"]
    cj --> bud["Budget.charge"]
    cj --> crec["CallRecorder.record"]
    jm --> sc
    sc --> rr["RunResults (runner fills records, values, cost, counts)"]
    rr --> fill["pipeline completes RunManifest<br/>(dataset, config_hash, judge versions, git, eval_fingerprint)"]
    fill --> aw["store.ArtifactStore.write_run(RunArtifacts)"]
    aw --> files[("run.json, results.parquet,<br/>responses.jsonl, llm_calls.parquet")]
```

Deterministic metrics always run first, and a hard fail on a case skips its judges to save cost. A
failed query is not dropped: the case gets the worst value for every metric and counts towards
`error_rate`. `BudgetExceeded` stops the run with `complete=false`, `stop_reason="budget_exceeded"`
and exit code 3, and the gate refuses incomplete runs.

## 2. `pruefstand gate`

```mermaid
flowchart TB
    cmd["cli/gate.py: gate --candidate [--baseline | --from-store]"] --> rg["pipeline.run_gate(candidate, baseline, cfg)"]
    rg --> rc["ArtifactStore.read_run(candidate)"]
    rg --> bs{{"--baseline given?"}}
    bs -->|"yes"| rb["ArtifactStore.read_run(baseline)"]
    bs -->|"no"| get["BaselineStore.get(eval_fingerprint, ref='main')<br/>plain files, sha256 manifest checked"]
    get -.-> gbs["GitBranchBaselineStore (index.json on private branch baselines, files in the data root on the VM disk)"]
    get -.-> lbs["LocalDirBaselineStore"]
    rc & rb & get --> chk{{"both complete, same eval_fingerprint,<br/>baseline error_rate <= 0.02?"}}
    chk ==>|"no"| err["raise GateInputError, exit 3"]
    chk -->|"yes"| tbl["pipeline builds ScoreTable per metric<br/>(cluster_ids, slices, higher_is_better)<br/>directions = MetricRegistry.directions()"]
    tbl --> eg["gate.evaluate_gate(baseline, candidate, policy, rng, directions=directions)"]
    eg --> hard["hard fails -> HardFailFinding<br/>(value 1; or unverifiable on a chunk-declaring target, D358)"]
    eg --> abs["absolute checks (max_value), overall slice only:<br/>decide_absolute -> FAIL if Wilson lower bound > max_value,<br/>WARN if lower bound > max_value/2 or paired max_drop WARNs"]
    eg --> sl["for each metric x slice: diffs oriented by higher_is_better"]
    sl --> few{{"n_clusters >= min_clusters (30)?"}}
    few -->|"no"| ins["INSUFFICIENT_DATA (report only)"]
    few -->|"yes"| nz{{">= 10 clusters with non-zero diff?"}}
    nz -->|"yes"| pcb["paired_cluster_bootstrap(diffs, cluster_ids, B=10000, rng)<br/>p = P*(mean_diff >= 0)"]
    nz -->|"no"| sign["sign_test_p(cluster mean diffs)"]
    pcb & sign --> rr{{"gated pair: p within 3 SE of a Holm threshold<br/>and drop > max_drop?"}}
    rr -->|"yes"| re["re-run with B = 200 000, same rng (D357)"]
    rr -->|"no"| gs
    re --> gs{{"gated pair?<br/>gated metric x (overall, tenant, lang, perturbed_all for retrieval metrics)"}}
    gs -->|"gated"| holm["holm_adjust ONCE over all testable gated pairs of the run (m pairs)"]
    gs -->|"informational"| bh["bh_adjust (q=0.10) -> notable=true, status always PASS"]
    holm --> dec["decide(r, max_drop, p_adjusted, alpha, warn_p, min_clusters, gated=True)<br/>FAIL: p_adj < 0.025 and mean_diff < -max_drop<br/>WARN: p_adj < 0.10 and mean_diff < -max_drop"]
    dec --> mde["minimum_detectable_effect(r.se, alpha, delta, m=m) -> SliceDecision.mde"]
    mde --> sd["SliceDecision(gated=true) -> GateReport.decisions"]
    bh --> sd2["SliceDecision(gated=false, mde=None) -> GateReport.notable_slices"]
    sd --> lc["gate/cause.py: likely_cause(decisions) -> CauseCode<br/>retrieval | generation | citation_format | language | refusal_policy | errors | mixed"]
    hard & abs & ins & sd & sd2 & lc --> gr["GateReport -> gate.json"]
    gr --> rep["cli/report.py: report --format md"]
    rep --> rpc["report.render_pr_comment(report, base, cand, report_url)<br/>redacted: no chunk text, canaries masked, MDE per gated metric"]
    rpc --> pub["GitHubPublisher.upsert_pr_comment (pruefstand-bot App token)"]
    gr --> st["GitHubPublisher.set_check(sha, status, summary)"]
    gr --> exit{{"status"}}
    exit -->|"PASS / WARN / INSUFFICIENT_DATA / UNSUPPORTED_CONFIG"| e0["exit 0"]
    exit ==>|"FAIL"| e1["exit 1"]
```

`evaluate_gate` is pure. It imports only `core`, takes two in-memory runs, a seeded
`numpy.random.Generator` and the `directions` mapping, and returns the same `gate.json` for the same
inputs. Metric direction reaches it as `directions` / `ScoreTable.higher_is_better`; `gate` never
imports `metrics`. Only testable gated pairs can FAIL or WARN, and Holm is applied **once** across all of
them (one family per run, SPEC §7.2). Non-gated slices are always PASS and appear as "notable slice
drops" (BH, q = 0.10) in `GateReport.notable_slices`. An absolute-check WARN makes the overall status
WARN. Exit codes: 0 pass/warn, 1 fail, 2 usage/config error, 3 runtime error (incl. `GateInputError`).

## 3. `pruefstand ingest`

```mermaid
flowchart LR
    cmd["cli/ingest.py: ingest --config corpus.yaml"] --> pi["pipeline/ingest.py"]
    raw[("data/raw/ (pinned via data/sources.yaml)")] --> l1["ingest.GiiXmlLoader.load"]
    raw --> l2["ingest.OldpLoader.load"]
    raw --> l3["ingest.EurLexLoader.load"]
    pi --> l1 & l2 & l3
    l1 & l2 & l3 --> at["ingest.assign_tenants(docs, TenantPlan)"]
    syn[("synthetic private docs")] --> pc
    at --> pc["attacks.plant_canaries(docs, rng)<br/>called by pipeline, not by ingest"]
    pc --> reg[("datasets/canaries/VERSION/canaries.json (public set)<br/>held-out set: git-ignored, then private repo only")]
    pi --> inj["attacks.make_injection_docs(...) (after T4.6)"]
    pc & inj --> c1["ingest chunkers .chunk(doc)<br/>citation_key via core.citations.normalise"]
    c1 --> wc["ingest.write_corpus(chunks, out_dir, corpus_version)"]
    wc --> out[("corpus/VERSION/TENANT.chunks.jsonl<br/>manifest.json")]
    wc --> cv["core.fingerprint.corpus_version(manifest, date_tag)"]
```

`ingest` and `attacks` are siblings and never import each other; `pipeline/ingest.py` is the one place
that combines them. Tenants are assigned before chunking so every `Chunk` carries its tenant. The
canary registry is kept out of the corpus directory that the rag-demo indexer reads.

## 4. `pruefstand build-dataset`

```mermaid
flowchart TB
    cmd["cli/build_dataset.py: build-dataset --config dataset.yaml"] --> bd["pipeline.build_dataset(cfg)"]
    bd --> corp[("corpus chunks")]
    corp --> gq["dataset.generate_qa(chunks, llm, model, prompt_version, rng)"]
    gq --> sup["dataset.check_support(candidate, chunk, llm, model)<br/>prompt support_check_de_v1"]
    sup --> ov["check_overlap(candidate, chunk, max_ngram_overlap)"]
    ov --> dd["dedupe(candidates, embed, max_sim=0.9)"]
    dd --> base["base TestCases<br/>base_id = id, cluster_id = source doc"]
    base --> pert["perturb.perturb_case / perturb_case_async<br/>keeps base_id and cluster_id"]
    bd --> att["attack TestCases from pipeline (injection, leak, filter bypass, system prompt)"]
    bd --> ref["refusal cases from GermanRAG"]
    base & pert & att & ref --> sp["assign_splits(cases, plan, rng)<br/>whole clusters per split<br/>SMOKE_LIVE = 20 fixture cases by rule<br/>ROBUST_PR = 40 bases x applicable perturbations (about 300 to 440)"]
    sp --> cb["closed-book run (T4.7b), tag closed_book_answerable"]
    cb --> val["validate_dataset(dir)"]
    val --> man[("datasets/NAME/VERSION/SPLIT.jsonl<br/>dataset_manifest.json (ReviewRound history)")]
    man -.->|"after model review + owner spot-check"| hf["export_hf(dir, repo_id, private, *, dry_run=False)<br/>writes dir/hf_export/, one config per licence"]
```

`dataset` imports `metrics`, `judges`, `perturb` and `llm` but never `ingest` or `attacks`; the attack
cases reach it from `pipeline`. Perturbed cases keep `base_id` (pairing) and `cluster_id` (the
bootstrap cluster), so `assign_splits` never splits a cluster across splits.

## 5. rag-demo `POST /v1/query`

```mermaid
flowchart TB
    app["create_app(cfg)"] --> ep["POST /v1/query(tenant_id, question, top_k, request_id)"]
    ep --> r["Retriever.retrieve(tenant_id, query, top_k)"]
    r --> a["GermanAnalyzer.tokens(query)"] --> s["SparseEncoder.encode(tokens)"]
    r --> d["DenseEncoder.encode([query])"]
    s & d --> qd["Qdrant Query API<br/>prefetch dense + sparse<br/>filter tenant_id in {tenant, shared_public} INSIDE each prefetch"]
    qd --> f["RRF fusion"]
    f --> rk{{"rerank enabled? (tier 2 only, tier 1 has no reranker)"}}
    rk -->|"yes"| rr["Reranker.rerank(query, hits, top_n)"]
    rk -->|"no"| hits["list of Hit"]
    rr --> hits
    hits --> g["Generator.answer(question, hits)"]
    g --> pf[("prompt file from rag.yaml")]
    g --> llm["generator<br/>llama.cpp OpenAI-compatible (CPU, tier 1) or Ollama native /api/chat (A40, via llm-proxy, bearer key)<br/>Qwen3 thinking disabled"]
    g --> out["answer, citations, chunks, refused, model, usage"]
```

The tenant filter is part of every prefetch, never applied after fusion or top-k. Mutation M8 moves it
after the cut to prove the gate catches it. The response returns retrieved chunks with their
`tenant_id`, which the `tenant_leak` metric checks; `canary_leak` checks answer and chunk text.

## 6. Core models

```mermaid
classDiagram
    class TestCase {
      id: CaseId
      base_id: CaseId
      cluster_id: str
      tenant: TenantId
      lang: Lang
      category: Category
      split: Split
      perturbation: str?
      tags: tuple
      gold_doc_ids
      gold_citations
      forbidden_strings
      injection_marker: str?
    }
    class TargetRequest {
      tenant_id
      question
      top_k
      request_id
    }
    class TargetResponse {
      answer
      citations
      refused: bool?
      model: str?
    }
    class RetrievedChunk {
      chunk_id
      doc_id
      tenant_id
      score
      rank
    }
    class Usage
    class TargetInfo {
      app_version
      git_sha
      image_digest
      config_hash
      corpus_version
      serving: dict
    }
    class CaseRecord {
      case_id
      latency_ms
      cached
      attempt
      error: str?
    }
    class MetricValue {
      metric
      metric_version
      value: float?
      status: MetricStatus
    }
    class ScoredCase
    class RunResults
    class RunArtifacts {
      results: RunResults
      root: Path
    }
    class RunManifest {
      run_id
      target_fingerprint
      eval_fingerprint
      dataset_version
      seed
      complete: bool
      stop_reason
      stack
      workload
      judge_mode
      judge_fallback: bool
      judge_degraded: bool
      judge_drift: bool
    }
    class CostSummary
    class ScoreTable {
      metric
      case_ids
      cluster_ids
      values
      slices
      higher_is_better: bool
    }
    class GateReport {
      status: GateStatus
      baseline_run_id
      candidate_run_id
      likely_cause: CauseCode?
      not_applicable_counts
      no_baseline: bool
    }
    class SliceDecision {
      metric
      dimension
      value
      status
      gated: bool
      notable: bool
      p_adjusted: float?
      mde: float?
      max_drop: float?
      max_value: float?
      n_clusters: int?
      informational_reason: str?
    }
    class BootstrapResult {
      mean_diff
      ci_low
      ci_high
      p_value
      se
      n_clusters
    }
    class HardFailFinding {
      rule
      case_id
      metric
      evidence
    }

    TargetResponse "1" o-- "0..*" RetrievedChunk : chunks
    TargetResponse "1" o-- "0..1" Usage
    CaseRecord "1" *-- "1" TargetRequest
    CaseRecord "1" o-- "0..1" TargetResponse
    ScoredCase "1" *-- "1" TestCase
    ScoredCase "1" *-- "1..*" MetricValue
    RunResults "1" *-- "1" RunManifest
    RunResults "1" *-- "0..*" CaseRecord
    RunResults "1" *-- "0..*" ScoredCase
    RunArtifacts "1" *-- "1" RunResults
    RunManifest "1" o-- "0..1" TargetInfo
    RunManifest "1" *-- "1" CostSummary
    ScoreTable ..> RunResults : built from
    GateReport "1" *-- "0..*" SliceDecision : decisions, absolute_checks, notable_slices
    GateReport "1" *-- "0..*" HardFailFinding
    SliceDecision "1" o-- "0..1" BootstrapResult
    TestCase ..> TargetRequest : becomes
```

All of these types are defined in `core` (interfaces.md, "Where types live"). A run is a `RunManifest`
plus one `CaseRecord` and one `ScoredCase` per test case. A `GateReport` compares two runs and refers to
them only by `run_id`. `TestCase.id` is never sent to the target, because `TargetRequest.request_id` is
random per call.
