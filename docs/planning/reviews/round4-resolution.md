# Round 4 resolution — owner answers + "real models, real CI" (binding)

Owner answers (2026-10-28): (1) no German annotator, "check the datasets"; (2) the cluster is reached
by plain SSH; (3) free APIs only, no paid APIs; (4)/(5) GitHub/HF usernames and hosting accounts will
be provided later (placeholders stay). And: **no fake LLM, no fake target — real LLMs and real CI in
GitHub.** This file overrides earlier resolutions where they conflict.

## V1 No fakes anywhere

| # | Decision |
| --- | --- |
| V1.1 | **Delete `FakeLLM`, `FakeTarget`, `Degradation`, `build_fake_target`, `fake_degradations_path`, `target.type == "fake"`** from every doc and prompt. ADR-0008 is rewritten as "Real-stack testing". |
| V1.2 | Allowed test doubles = none for models or the target. What remains is: (a) **pure-function unit tests on real inputs** (citation parser on real law text, perturbations on real questions, hashing, config); (b) **statistical validation of `gate.stats` on simulated numbers**: this tests the maths (type-I error, power), not the product, and stays; (c) **recorded real responses** ("cassettes", `vcrpy`/`respx`): every cassette is captured from a real model call by `make cassettes` (real LLM), committed under `tests/cassettes/`, re-recorded weekly by `cassettes.yml`, and is used only for fast parser/retry tests of `llm/`. Every behaviour covered by a cassette is **also** covered by a live test in CI. |
| V1.3 | Failure demonstrations use the **real rag-demo with real bug switches** in `rag.yaml` (the mutation mechanism, real code paths): `tenant_filter: inside | post_topk` (M8 bug), `shared_public_merge: filtered | unfiltered` (M9 bug), `reranker: on|off`, `prompt_file` variants without the citation / refusal / injection-guard instruction, `answer_language: auto | en` (M12). These switches are part of rag-demo from its first version (T1.13) and of the mutation benchmark later. |

## V2 Real CI tiers (supersede earlier tier definitions)

| Tier | Where | What runs (all real) | When |
| --- | --- | --- | --- |
| 0 Code | GitHub-hosted | lint, types, arch, pure unit tests, statistical validation, cassette tests, contract tests, docs, image builds + scans | every push/PR, forks included |
| **1 Live** (`live-e2e.yml`) | GitHub-hosted, 4 vCPU / 16 GB, CPU only | docker compose: **real Qdrant + real rag-demo + real generator** (llama.cpp server, German-capable ~1.5–4B instruct GGUF Q4_K_M, pinned in T1.13) + **real embeddings** (small multilingual model on CPU, pinned in T1.13) on the **real 5-law slice corpus**; **real judge** = GitHub Models via `GITHUB_TOKEN` (`permissions: models: read`, free tier), a different family from the generator; `pruefstand run --split smoke` + `gate` against the main baseline; real PR comment | every same-repo PR + push to main + nightly |
| 2 Full | private executor on the A40s (unchanged design) | core + robust_pr with the real ~14B generator and the PR judge | trusted PRs (label), main, nightly |

| # | Decision |
| --- | --- |
| V2.1 | Tier-1 budget ≤ 30 min. The index for the slice corpus is built in the job and cached via `actions/cache`, keyed by corpus version + embedding model. Model files are cached the same way (`~/.cache/pruefstand/models`, keyed by model SHA-256). |
| V2.2 | Tier-1 baseline = artefact of the latest successful `live-e2e.yml` run on `main` (downloaded by run id through the API; produced only by main, so trusted). Main also refreshes it nightly. |
| V2.3 | Fork PRs: `GITHUB_TOKEN` has no `models` permission → tier 1 runs with deterministic metrics only, plus a CPU judge (llama.cpp, second small model of another family). The comment says so. |
| V2.4 | GitHub Models rate limits: judgments are cached per (answer, judge, prompt version) in `actions/cache`, so only changed answers are re-judged. Use a low-tier model to stay inside the free daily quota. On HTTP 429 the run falls back to the CPU judge and marks `judge_fallback=true` in run.json (never a silent change). The quota numbers are verified in T0.6 and written to gpu-cluster.md / ci-cd.md. |
| V2.5 | The walking skeleton (M1) is now **real end to end**: M1 = tier 1 green on a real PR with a real comment, and the three demo PRs (reranker off → FAIL or WARN, whitespace → PASS, `tenant_filter: post_topk` → hard FAIL) run in tier 1. |

## V3 Task changes (TASKS + prompts)

| ID | New content |
| --- | --- |
| T1.3 | HTTP adapter + target API v1 contract tests (schemathesis against the real rag-demo app object from T1.13 once it exists; until then against the OpenAPI file). No FakeTarget. |
| T1.4 | `llm` with **real backends from day 1**: `LiteLLMBackend` (OpenAI-compatible: llama.cpp server, vLLM, GitHub Models), Budget (USD **and** requests/tokens), CallRecorder, PromptRegistry, cassette recording (`make cassettes`). Live tests marked `live` run against a llama.cpp container in CI. T5.1 keeps only hardening (JSON repair, retries tuning, cost table, provider policy). |
| T1.11 | 40 hand-written German cases on the **real 5-law slice** (KSchG §§ 1–4, ArbZG §§ 3–5, BGB §§ 620–626, BDSG §§ 26, DSGVO Art. 5–6 DE + EN) with real gold doc ids and citations; owner spot-check optional. E2E tests (`e2e` marker) run the real stack: good config → PASS on smoke vs itself; `tenant_filter: post_topk` → hard FAIL; prompt without citation instruction → citation drop flagged. |
| T1.12 | GitHub Action + `live-e2e.yml` (tier 1) + `action-selftest.yml` using the real stack. |
| **T1.13 (new)** | rag-demo **v0**: FastAPI `/v1/*`, BM25 (German analyzer v0: NFC, lowercase, umlaut fold) + small dense model, Qdrant, llama.cpp generator, bug switches V1.3, `rag.yaml`; compose profile `live`; model pins (generator GGUF, embeddings) with SHA-256. Depends on T1.1, T2.1, T2.2, T0.3. T3.2–T3.6 later extend it (hybrid, reranker, A40 generator) instead of starting from scratch. |
| T2.1/T2.2 | Pulled earlier (parallel lane after T0.1) because T1.13 needs the 5-law slice. |
| T5.3 | **Replaced**: "Calibration label sets from existing human data" (no annotator): MEMERAG-DE (faithfulness), GermanQuAD constructed pairs (correctness), GermanRAG (refusal), constructed consistency pairs. Human labels become optional (`T5.3-opt`). |
| T5.4 | Calibration on those sets (see V4). |
| T6.3 | likely_cause is tested on real bug switches (V1.3) in tier 1, not on FakeTarget. |
| T0.6 | Also: measure GitHub Models free quotas from a test workflow; check that a user-level runner process and rootless Docker or Podman are allowed over **plain SSH** (no Slurm). |
| everywhere | Remove FakeTarget/FakeLLM wording; e2e and simulation fixtures that used FakeTarget switch to the real stack (e2e) or to `gate.stats` simulations (statistics). |

## V4 Judge calibration without a German annotator

| Set | Source | Labels | Use |
| --- | --- | --- | --- |
| Faithfulness | **MEMERAG** German subset (amazon-science/MEMERAG, ACL 2025; 5 expert annotators, majority vote; CC BY-NC 4.0) | `Supported` → 2, `Not Supported` → 0, "Challenging to determine" dropped | Binary κ: judge score 2 vs < 2. **Download-only, never redistributed, never used for training**; numbers and the method are published, the data is not. |
| Answer correctness | **GermanQuAD** test (3-way human answers) | constructed pairs: another annotator's answer = correct (2); the answer to a different question about the same article = wrong (0); a number/date-swapped answer = wrong (0) | Binary κ + accuracy |
| Refusal | **GermanRAG** unanswerable third | by construction | Accuracy, false-refusal rate |
| Consistency | GermanQuAD | paraphrased answer pairs (consistent) vs answers to different questions (inconsistent) | Binary κ |

Labels made "by construction" are documented as such in the report (limitation: no human partial-credit
labels). If a German annotator turns up later, `T5.3-opt` adds 100 hand labels as a check.

## V5 Free-only providers

| # | Decision |
| --- | --- |
| V5.1 | Default providers: local vLLM on the A40s, llama.cpp on CPU in CI, **GitHub Models free tier**. `budget.max_usd_per_run = 0`; `LLMClient` refuses any provider not in `allowed_providers` (default `hosted_vllm`, `openai_compatible_local`, `github`), and any paid provider unless `allow_paid: true` (off). |
| V5.2 | Optional free tiers, opt-in per config: Mistral (free "Experiment" tier), Google Gemini free tier, Groq free tier, OpenRouter `:free` models. **Rule:** private docs, canaries (public and held-out) and the private executor's data are **never** sent to an external free API (free tiers may train on inputs); only public law text and public test cases may be. Enforced by a check in `LLMClient`: requests whose `prompt_id` belongs to `datagen.private_docs` or that contain a registered canary are blocked for external providers. |
| V5.3 | Test generation (T4.2) and LLM perturbations (T4.5) use the local 70B-class model on the A40s; GitHub Models is used for a 10 % cross-check sample. |

## V6 Licensing correction (checked on the HF dataset cards, 2026-10-28)

`deepset/germanquad` and `deepset/germandpr` list **CC BY 4.0** (not CC BY-SA). GermanRAG: verify its
card in T2.1; if it inherits only from GermanDPR, it is CC BY 4.0 too. → The `germanquad_derived`
config is CC BY 4.0 unless GermanRAG says otherwise. MEMERAG: CC BY-NC 4.0, download-only. Update
DATA_LICENSES.md, SPEC §2, ADR-0015 and the T2.1 checks (the script records the license field from
each card and fails on a mismatch with DATA_LICENSES.md).

## V7 Cluster over plain SSH

No Slurm. T0.6 records: SSH host, whether user-level services may run, Docker vs rootless Docker vs
Podman, GPU access for the user, outbound HTTPS. The executor design (pull-based, private repo,
user-level runner) needs no root. If neither rootless Docker nor Podman is available, the fallback is
Apptainer containers started by the runner user; T6.2a documents both paths.
