# Round 5: cold read of prompts T0–T4 (reviewer A)

Scope: `prompts/T0.*` to `prompts/T4.*` (43 prompts), each read as if it were the only task, against
`CLAUDE.md`, `docs/decisions.md`, `docs/architecture/interfaces.md`, `tasks/TASKS.md` and
`prompts/_TEMPLATE.md`. T5–T10 were out of scope. Every issue below was fixed in place.

| ID | Issues found | Fixed |
| --- | --- | --- |
| T0.0 | step and done-when line about moving a `.review` folder into the review history path; the placeholder check did not cover `<HF_USER>` | yes |
| T0.1 | test-table paths ambiguous (`tests/unit/…`, which could mean root `tests/`); `schemas` stub would break once T1.1 adds `core.schema` but the CLI command arrives only in T1.10; `cassettes` stub had nothing to call (T1.4 would have had to redefine a §3 target); `.gitignore` `corpus/` blocked the committed slice corpus | yes |
| T0.2 | concurrency pointed to §5 (it is §6); `e2e` job in `ci.yml` not in ci-cd.md (e2e runs in `live-e2e.yml`); required-check list missing `live-e2e / gate`; `models: read` allowlist would have rejected `action-selftest.yml` and `cassettes.yml` (security.md X2); `cassettes.yml` permissions contradicted ci-cd.md; superseded D31; zizmor line missing `[NET]`; script path differed from ci-cd.md | yes |
| T0.3 | `check_compose.py` digest rule would fail `build:`-only services; superseded D32 cited | yes |
| T0.4 | strict mode could push the session to edit historical, non-nav docs | yes |
| T0.5 | S9 asked for a paid Anthropic key (D86); said GitHub Models is never used in public workflows (it is, tier 1); "branches up to date" missing vs ci-cd.md §5; superseded D31 | yes |
| T0.6 | model Sonnet vs TASKS Opus; asked for a "new section" although gpu-cluster.md §0 F1–F11 exists; disk threshold 300 GB vs F7 200 GB; ci-cd quota section did not exist | yes |
| T1.1 | phase named "Walking skeleton" (superseded D2); D30 superseded; `bytes` encoding differed from interfaces.md | yes |
| T1.2 | paid `anthropic_api_key` setting and paid/Ollama provider prefixes and test ids; `TargetConfig` signature differed from interfaces; `LLMPolicyConfig` and `PruefstandConfig.llm` missing (owner unclear vs T1.4); `judge.nightly`/fallback judge unspecified in the example | yes |
| T1.3 | `source: openapi-example` marker had no defined place inside response JSON; example doc id `bgb-622` differs from the real T2.2 id scheme; bare `pytest` | yes |
| T1.4 | LLM cache key had 6 parts vs the 8-part key (D35, interfaces §8); Gemini listed as paid (D86: free tier); `LLMError(transient, status)` not in core; `LLMPolicyConfig` owned twice; `make cassettes` would redefine a §3 target; a real 503 cassette had no recording method | yes |
| T1.5a | `Citation` defaults differed from interfaces.md | yes |
| T1.5b | cited a review file ("technical review D2"); `MetricRegistry.default()` not marked as an addition | yes |
| T1.6 | testing-strategy §3.5 cited for the simulation harness (it is §3.4); D60 superseded | yes |
| T1.7 | same §3.5 → §3.4 references; D60 superseded | yes |
| T1.8 | `results.parquet` said 11 columns (interfaces §8 has 13); `query_other_tenant.json` consumed but created by no task; bare `pytest` | yes |
| T1.9 | `fmt_usd` produced `$0.18` vs SPEC §7.6 `0 USD`; "question text" is not an input of the renderer; 6 vs 7 snapshot scenarios; bare `pytest` | yes |
| T1.10 | `--tier` missing `bench`; MDE evidence value wrong (0.040 → 0.042); `bug_citations` expectation claimed a sign test with 12 non-zero clusters; cassette origin contradicted itself (T1.13 vs this task); `hf://` promised in T4.7a (no task implemented it); doc ids differed from T2.2; untagged Docker line | yes |
| T1.11 | leak-probe regex differed from the T1.5b semantic-canary form; bare `pytest` | yes |
| T1.12 | `models: read` "live-e2e only" contradicted ci-cd.md (action-selftest has it); baseline lookup rule self-contradictory (push only vs push+schedule); job layout differed from ci-cd.md (ci-cd row updated to T1.12's layout) | yes |
| T1.13 | committed `corpus/slice_v1` but `corpus/` is git-ignored; doc/chunk ids differed from T2.2; `parallel_id` scheme unspecified; contract re-recording did not cover `_meta.json` / T1.8's example; bare `pytest` | yes |
| T2.1 | "decision V6" does not exist (D89); `data/README.md` from T0.1 does not exist; root `Makefile` edits instead of `mk/`; wiring into `make check` would redefine a §3 target; manifest count 57 omitted the GitHub source (58) | yes |
| T2.2 | full-corpus evidence line untagged (needs T2.1 downloads) | yes |
| T2.3 | non-standard env tag `[NET: …]` | yes |
| T2.4 | `normalise` signature missing `granularity`; edited test file not listed; non-standard env tag | yes |
| T2.5 | circular `corpus_version` / `write_corpus` order undefined; offline fixture test marked `e2e` (never runs in CI); fixture config path missing from files; non-standard env tag | yes |
| T2.6 | Context (A40 70B only) vs Constraints (A40 or llama.cpp) contradiction; recreated core models from T1.1; `semantic_variants` not declared as an interface addition; root `Makefile` edit | yes |
| T3.1a | "replace T0.3's placeholder GPU services" (none exist); root `Makefile` edit; untagged GPU evidence line | yes |
| T3.1b | root `Makefile` edit; GerDaLIR download needs `[NET]`; pinning evidence untagged | yes |
| T3.2 | used T3.1b pins without depending on T3.1b; "seven" bug switches (eight configs); wrong compose file name; bare `pytest` | yes |
| T3.3 | package `analysis/` collides with T1.13's `analysis.py`/`sparse.py`; compound/analyzer test rows ambiguous under folding and stemming | yes |
| T3.4 | `--encoder hash` is a simulated embedding (ADR-0008); package `index/` collides with `index.py`; CLI entry point missing; root `Makefile` edit | yes |
| T3.5 | tenant guard would neutralise the real leak bug switches the gate must catch; old `retrieve.py` not removed; hash encoder in evidence; compose/model-pin edits not listed | yes |
| T3.6 | paid "premium" config; wrong prompt/config paths; would edit immutable `answer_de_v1.txt`; two class names for one generator; unrecordable 500 cassette; GPU evidence used the wrong compose command | yes |
| T3.7 | CI wiring contradictory (live-e2e vs new ci.yml job vs aggregator); probe matrix could not reach 50 with 1 canary per tenant; rag-demo tests had no number-word matching without pruefstand; root `Makefile` edit | yes |
| T4.1 | fixture path `datasets/fixtures/v1` (it is `slice_v1`); "TestCase gains" fields that exist since T1.1 | yes |
| T4.2 | non-standard tag `[NET or GPU]`; tests not in the file list; `make cassettes` had no dataset section | yes |
| T4.3 | non-standard env tag; live test not listed; NFC/NFD test row unreadable | yes |
| T4.4 | read `core/models/perturb.py` and the `Perturbation` protocol that no earlier task creates | yes |
| T4.5 | `LLMPerturbation` protocol file not listed; non-standard env tags; cassette recording unspecified | yes |
| T4.6 | `attack_set_version` stored in manifest fields that do not exist (`extra="forbid"`); `InjectionPlacement` ownership unclear; semantic probe form | yes |
| T4.7a | typo; two different `source` values for the same fix; `--only` flag needed by T4.7b missing; root `Makefile` edit; tag placement | yes |
| T4.7b | `--only` not in T4.7a; non-standard env tag; `hf://` loading (SPEC §5.6) owned by no task, so it was added here as S6 | yes |

## Edits outside the prompts

- `CLAUDE.md` §3: one sentence saying task Make targets go into `mk/<area>.mk`.
- `docs/architecture/interfaces.md` §2: the `stable_hash` bytes encoding is `{"__bytes__": hex}` (matches T1.1).
- `tasks/TASKS.md` T0.5 row: the required-check order (`build-images / build` T0.3, `docs / build` T0.4).
- `docs/engineering/ci-cd.md`: the workflow-guard script path; `build-images.yml` jobs (`compose-lint`,
  `build-image`); the `live-e2e.yml` job layout from T1.12; `examples/live/pruefstand.yaml` instead of `pruefstand.live.yaml`.
- `docs/engineering/security.md`, `docs/engineering/testing-strategy.md`, `docs/architecture/sequences.md`:
  the same config path.
