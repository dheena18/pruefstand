# Coding standards

Binding summary: `CLAUDE.md` §5. This file has the details and the exact tool configuration. T0.1 copies
§1.1 into the root `pyproject.toml` **verbatim** (D127); a task's own rule list never replaces it. The coverage
gate is defined only in `CLAUDE.md` §6 (D130). Round-9 changes (D176, D177) are marked **R9**; round-12 changes
(D266, D250) are marked **R12**.

## 1. Python

### 1.1 Tool configuration (root `pyproject.toml`)

```toml
[tool.ruff]
target-version = "py312"
line-length = 100
src = ["packages/pruefstand/src", "apps/rag-demo/src"]
extend-exclude = ["*.md"]       # ruff >= 0.17 formats/lints Python blocks in Markdown; docs hold pseudo-code (T0.1)

[tool.ruff.lint]
preview = true                  # needed for PLR0917 (max-positional-args)
explicit-preview-rules = true   # no other preview rule is switched on implicitly
select = [
  "E", "W", "F",      # pycodestyle, pyflakes
  "I",                # isort
  "N",                # pep8-naming
  "UP",               # pyupgrade
  "B",                # bugbear
  "A",                # builtins shadowing
  "C4",               # comprehensions
  "C90",              # mccabe complexity
  "SIM",              # simplify
  "RET",              # return hygiene
  "ARG",              # unused arguments
  "PTH",              # pathlib over os.path
  "ERA",              # commented-out code
  "PL",               # pylint subset (PLR0913 too-many-args etc.)
  "TRY",              # exception hygiene
  "EM",               # exception messages not inline f-strings
  "S",                # bandit security
  "T20",              # no print
  "DTZ",              # timezone-aware datetimes
  "RUF",              # ruff-specific (incl. ambiguous unicode — see per-file ignores)
  "ASYNC",            # async pitfalls
  "PT",               # pytest style
  "D",                # pydocstyle
  "ANN",              # annotations
  "FBT",              # boolean positional args
  "TID",              # banned imports (see below)
  "PLR0917",          # too many positional args (preview rule, D127)
]
ignore = ["D105", "D107", "TRY003", "PLR2004"]   # TRY003: ConfigError("…") messages are prescribed by the prompts
allowed-confusables = ["–", "−", "„", "“", "‚", "‘", "’"]   # German quotes, en dash, minus sign in src strings/docstrings

[tool.ruff.lint.mccabe]
max-complexity = 10

[tool.ruff.lint.pylint]
max-args = 8                    # longer interface signatures: inline noqa + "Allowed long signatures" below (R9 X4.1)
max-positional-args = 5         # PLR0917: long signatures stay keyword-only
max-statements = 40

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"litellm".msg = "Use pruefstand.llm.LLMClient (ADR-0009)"
"openai".msg = "Use pruefstand.llm.LLMClient (ADR-0009)"
"anthropic".msg = "Use pruefstand.llm.LLMClient (ADR-0009)"
"yaml.load".msg = "Use yaml.safe_load"
"random".msg = "Pass a numpy.random.Generator"
"numpy.random.seed".msg = "Pass a numpy.random.Generator"
"numpy.random.rand".msg = "Pass a numpy.random.Generator"

[tool.ruff.lint.per-file-ignores]
"**/tests/**" = ["S101", "D", "ANN", "PLR2004", "ARG", "RUF001", "RUF002", "RUF003"]   # German test strings (D127)
"**/llm/backends/litellm.py" = ["TID251"]
"scripts/**" = ["T201"]            # CLI scripts may print
"tools/**" = ["T201"]
"experiments/**" = ["T201"]
"benchmarks/**" = ["T201"]
"data/**" = ["T201"]
# R9 X4.1: signatures fixed by interfaces.md that break a lint rule use an INLINE `# noqa: <code>` on the def line,
# never a per-file ignore; every such def is in the "Allowed long signatures" table below.

[tool.pytest.ini_options]
addopts = "--import-mode=importlib --strict-markers"
# testpaths: the append-only list from D71 (set in T0.1), plus (R11 D232) infra/vm/tests, infra/cluster/tests,
#   infra/gate-executor/orchestrator/tests, infra/gate-executor/llm-proxy/tests (appended by T0.7 / T3.1a / T6.2a)
# R9 X4.2 (D177): ONE root list, identical in pythonpath and [tool.mypy] mypy_path; T0.1 copies both verbatim
pythonpath = ["packages/pruefstand/src", "apps/rag-demo/src", "packages/pruefstand/tests", "apps/rag-demo/tests",
              "scripts", "data", "experiments", "tools", "action", "infra/gpu", "benchmarks",
              "infra/vm", "infra/cluster", "infra/gate-executor/orchestrator", "infra/gate-executor/llm-proxy"]
              # R11 Y6.4 (D232): the last four roots hold the Python helpers of T0.6/T0.7/T3.1a/T6.2a
# make test / make coverage add: --doctest-modules packages/pruefstand/src   (D128)
# make test / make coverage export LITELLM_LOCAL_MODEL_COST_MAP=True (no remote cost-map fetch in offline runs)
markers = [
  "integration", "e2e", "live", "gpu", "slow", "network",
  "quarantine: flaky test with a linked issue, @pytest.mark.quarantine(issue=N)",   # R9 (D9-22)
]

[tool.mypy]
python_version = "3.12"
strict = true
explicit_package_bases = true
mypy_path = ["packages/pruefstand/src", "apps/rag-demo/src", "packages/pruefstand/tests", "apps/rag-demo/tests",
             "scripts", "data", "experiments", "tools", "action", "infra/gpu", "benchmarks",
             "infra/vm", "infra/cluster", "infra/gate-executor/orchestrator",
             "infra/gate-executor/llm-proxy"]   # = pythonpath (R9 X4.2, R11 D232)
warn_unreachable = true
enable_error_code = ["ignore-without-code", "redundant-expr", "truthy-bool", "possibly-undefined"]
plugins = ["pydantic.mypy"]

[tool.pydantic-mypy]
init_forbid_extra = true
init_typed = true
warn_required_dynamic_aliases = true
```

Module names must be unique across the roots above: no two roots may expose the same top-level module (e.g.
`infra/gpu/schema.py` is named `catalogue_schema.py`, and `benchmarks/mutations/schema.py` is imported as
`mutations.schema`; R11 D232: the proxy module is `infra/gate-executor/llm-proxy/llm_proxy.py`, never `app.py`,
so it cannot clash with `infra/gpu/rerank/app.py`; the T0.6 summariser is imported as `feasibility.summarise` from
the `infra/cluster` root). `scripts/check_test_locations.py` (T0.1) fails on a clash across all roots (R9 D9-05).
Directory names with a hyphen (`gate-executor`, `llm-proxy`) are never package names: they are roots, so modules
inside them are imported by their own names.

**Test directories and type checking per root (R12 N6.3, D266; DEV12-04).**

- Tests of each import root stay in `<root>/tests/` (no `__init__.py`), e.g. `scripts/tests/`, `infra/vm/tests/`,
  `infra/gate-executor/llm-proxy/tests/`; a sub-area of a root may have its own `<root>/<area>/tests/` (e.g.
  `scripts/dashboard/tests/`). The two package test roots (`packages/pruefstand/tests`, `apps/rag-demo/tests`) keep
  their `unit/`, `integration/`, `contract/`, `live/`, `gpu/`, `e2e/` layout.
- pytest runs with `--import-mode=importlib`, so test-module basenames (incl. `conftest.py`) **may repeat** across
  roots (two `test_health.py` in different roots are fine).
- `make typecheck` runs mypy **once per root**, never over all roots in one invocation, so two roots' `tests`
  directories can never collide as `tests.*` in one mypy run:

  ```make
  typecheck:
  	@$(foreach r,$(EXISTING_ROOTS),echo ">> mypy $(r)"; uv run mypy $(r) || exit 1;) true
  ```

  `EXISTING_ROOTS` is the §1.1 root list (same order) filtered to the roots that exist, expanded by Make so that
  `make -n typecheck` shows one `uv run mypy <root>` per root (`--strict` comes from `[tool.mypy]`); the `[tool.mypy]` config above is shared by every
  invocation, and a root that has no `.py` file yet is skipped. `packages/pruefstand/tests` and `apps/rag-demo/tests`
  are separate runs, so their `unit.*` modules never meet.
- The module-uniqueness rule above applies to **non-test** modules only. `scripts/check_test_locations.py` (T0.1)
  accepts a test file when it lies under `<root>/tests/` or `<root>/<area>/tests/` for any root in the CLAUDE.md §3 /
  §1.1 list (or under the two package test roots), fails on a test file anywhere else, and ignores `tests`
  directories when it checks top-level module clashes.

#### Allowed long signatures (R9 X4.1, D176)

The only defs that may carry these `noqa` codes. Each carries the inline comment `# noqa: <codes>` on its `def`
(or `class` for `__init__`) line; a new entry needs an interfaces.md change (CLAUDE.md §1.5). `make lint` passes
with exactly these exceptions; review rejects any other `noqa` for `PLR0913`, `PLR0917`, `A002`, `A003`, `FBT001`,
`FBT002`.

| Symbol (interfaces.md) | File | `noqa` codes | Why |
| --- | --- | --- | --- |
| `eval_fingerprint(*, dataset_name, …, judge_serving, judge_epoch, metric_versions, corpus_version, block, judged_subset, stratum)` (§2) | `core/fingerprint.py` | `PLR0913` | 12 keyword-only args (R9 X3.3; R12 N1.3 adds `block`, `judged_subset`; R13 P4.3 adds `stratum`, D298) |
| `Runner.__init__(adapter, metrics, judges, cache, budget, cfg, *, hard_fail)` (§8) | `runner/runner.py` | `PLR0917` | 6 positional |
| `cluster_bootstrap_ci(stat, df, cluster_col, n_resamples, confidence, rng)` (§6) | `judges/calibration.py` | `PLR0917` | 6 positional |
| `CassetteRecorder.__init__(self, dir, mode)` (§3) | `llm/cassettes.py` | `A002` | `dir` shadows a builtin |
| `simulate_paired(n_clusters, cluster_size, true_delta, *, sigma_d, icc, kind, discordance, rng, cluster_sizes, n_sims)` (testing-strategy §3.4) | `packages/pruefstand/tests/testsupport/sim_data.py` | `PLR0913` | 10 args: 8 of §3.4 + `cluster_sizes` (T1.6 prompt) + `n_sims` (vectorised draws); test helper, keyword-only after 3 positionals |
| `generate_qa(chunks, llm, model, prompt_version, rng, *, concurrency, stats, sink, skip)` and `generate_qa_pairs(pairs, …)` (§14) | `dataset/generate.py` | `PLR0913` | the 5 interface arguments + 4 keyword-only run options (T4.2, D785): 9 args |
| `validate_dataset(dir)` (§14) | `dataset/validate.py` | `A002` | `dir` |
| `export_hf(dir, repo_id, private, *, dry_run)` (§14) | `dataset/export_hf.py` | `A002`, `FBT001` | `dir`; positional bool `private` |
| `PromptTemplate.render(**vars)` (§3) | `core/models/llm.py` | `A002` | `vars` |
| `MetricRegistry.all()` (§5) | `metrics/registry.py` | `A003` | method named `all` |
| `GermanAnalyzer.__init__(compound_split, stemmer, fold_umlauts=True)` (§16) | `apps/rag-demo/src/rag_demo/analysis/analyzer.py` | `FBT001`, `FBT002` | positional bools |
| `decide(r, *, max_drop, p_adjusted, alpha, warn_p, min_clusters, gated)` (§9) | `gate/decision.py` | none today (7 args ≤ 8) | listed so a future field is caught in review |
| `run_eval(cfg, *, tier, out, block, judged_subset, stratum)` (§15) | `pipeline/run.py` | none today (6 args ≤ 8; R13 P4.3 adds `stratum`) | listed so a further selector is caught in review |
| `GitHubPublisher.post_status(self, sha, state, description, context="pruefstand/gate")` (§10) | `report/github.py` | none (4 positional ≤ 5; R13 P4.2, D297) | listed so a new parameter goes keyword-only |
| `labels_document() -> LabelsDocument` (§10) | `report/labels.py` | none (R9 X5.3 typed it; a bare `dict` failed `mypy --strict`) | – |

Test helpers are not exempt: testing-strategy §3.4's `simulate_paired(n_clusters, cluster_size, true_delta, *,
sigma_d, icc, kind, discordance, rng)` is keyword-only after three positionals (R9 D9-04), and tests pass booleans by
keyword (`export_hf(build_dir, "o/r", private=True, dry_run=True)`, `FBT003`).

### 1.2 Naming

| Thing | Convention | Example |
| --- | --- | --- |
| Module | `snake_case`, a noun naming its one responsibility | `citations.py`, `bootstrap.py` |
| Class | `PascalCase`; Protocols named for their role | `TargetAdapter`, `HttpTargetAdapter` |
| Function | `snake_case`, verb first | `extract_citations`, `paired_cluster_bootstrap` |
| Async function | `a`-prefix only when a sync twin exists | `complete` / `acompute` |
| Constant | `UPPER_SNAKE` | `DEFAULT_RESAMPLES = 10_000` |
| Metric / perturbation names | stable `snake_case` strings from interfaces.md | `citation_f1`, `umlaut_translit` |
| Prompt file | `<purpose>_<lang>_v<N>.txt` | `faithfulness_de_v1.txt` |
| Test | `test_<unit>_<behaviour>` | `test_decide_returns_fail_when_upper_below_neg_delta` |

Domain words stay German where they are terms of art: `Tatbestand`, `Absatz`, `Kanzlei`. Code
identifiers are English except for those terms.

### 1.3 Size and shape limits

| Limit | Value | Enforced by |
| --- | --- | --- |
| File length | ≤ 300 lines | `scripts/check_code_limits.py` in `make file-size`; a module that would grow past it becomes a package with an `__init__.py` that only re-exports, e.g. `core/config/` (`run.py`, `target.py`, `gate.py`, `build.py`; R13 DEV13-13, D313) |
| Function length | ≤ 50 lines | ruff `PLR0915` (statements) + review |
| Cyclomatic complexity | ≤ 10 | ruff `C901` |
| Arguments | ≤ 8, of which ≤ 5 positional (use a model or a keyword-only `*`) | ruff `PLR0913`, `PLR0917` |
| Nesting | ≤ 3 levels | review |

### 1.4 Docstrings (Google style)

Every public module, class and function has one. A statistics or metric function also carries a
worked numeric example as a doctest. Doctests run in `make test` and `make coverage` via
`--doctest-modules packages/pruefstand/src` (D128), so a wrong worked example fails CI.

Scripts and other repo code outside packages (`scripts/`, `data/`, `experiments/`, `tools/`, `action/`,
`infra/gpu/`, `benchmarks/`, `infra/vm/`, `infra/cluster/`, `infra/gate-executor/orchestrator/`,
`infra/gate-executor/llm-proxy/`; R11 D232) are on pytest's `pythonpath` **and** mypy's `mypy_path` (one list, §1.1; D129, R9 X4.2);
their tests import them in-process by module name (e.g. `from check_code_limits import main` for
`scripts/check_code_limits.py`), never by editing `sys.path`. Modules for optional extras
(`report/evidence_pdf.py`, `pruefstand.mcp`, framework adapters) import their framework lazily inside functions, so
`--doctest-modules` works with `make install` (`--all-extras`).

```python
def citation_f1(predicted: Sequence[str], gold: Sequence[str]) -> float:
    """F1 between normalised predicted and gold citations.

    Args:
        predicted: Normalised citations extracted from the answer.
        gold: Normalised gold citations of the test case.

    Returns:
        F1 in [0, 1]. Returns 1.0 if both are empty, 0.0 if exactly one is empty.

    Raises:
        ValueError: If a citation is not normalised.

    Example:
        >>> citation_f1(["§ 622 BGB"], ["§ 622 BGB", "§ 623 BGB"])
        0.6666666666666666
    """
```

### 1.5 Data structures

- Cross-module data uses Pydantic v2 models with `ConfigDict(frozen=True, extra="forbid")`.
- Use tuples, not lists, in frozen models.
- Datetimes are timezone-aware UTC (`datetime.now(tz=UTC)`); the clock is injected where results depend on it.
- Large tables use `polars.DataFrame`. NumPy arrays are only for maths inside `gate` and `judges.calibration`.
- No mutable default arguments. No module-level mutable state except registries filled at import.

### 1.6 Errors

| Rule | Detail |
| --- | --- |
| Hierarchy | Everything raised to callers subclasses `PruefstandError` (`ConfigError`, `TargetError`, `LLMError` (+ `PolicyViolation`, `QuotaExhausted`, R9), `BudgetExceeded`, `DatasetError`, `StoreError`, `GateInputError`, `PromptError`, `CorpusMismatch`) |
| Wrap at the boundary | Wrap external exceptions (`httpx`, `litellm`, `qdrant_client`) once at the adapter boundary, chained with `raise … from e` |
| No swallowing | `except Exception` is allowed only at the runner per-case boundary, where it records `CaseRecord.error`, and in the CLI top level |
| Messages | Say what failed, the input id, and what to do. Never include secrets or full document text |
| Timeouts | Every network call has an explicit timeout; retries use exponential backoff with jitter, max 3 |
| CLI exit codes | `0` pass/warn, `1` gate fail, `2` usage/config error, `3` runtime error |

### 1.7 Logging fields

`get_logger(__name__).info("event_name", **fields)`. The event is a `snake_case` verb phrase.

| Field | When |
| --- | --- |
| `run_id` | always inside a run (bound once with `bind_contextvars`) |
| `case_id`, `tenant` | per-case events |
| `metric`, `metric_version` | metric events |
| `model`, `role`, `prompt_id`, `prompt_version` | LLM events |
| `duration_ms` | any timed operation |
| `error_type`, `attempt` | failures and retries |
| `cached` | cache hits |

Never logged: API keys, auth headers, full prompts or answers above DEBUG, another tenant's text.

### 1.8 Module README template (`<module>/README.md`, ≤ 40 lines)

```markdown
# pruefstand.<module>

**Responsibility:** <one sentence>
**Layer:** <layer name from CLAUDE.md §4> · **May import:** <modules> · **Must not import:** <modules>

## Public API
| Name | Kind | Purpose |
| --- | --- | --- |

## Data flow
<3–6 lines or a small Mermaid diagram; link to docs/architecture>

## Invariants
- <e.g. pure, no I/O; deterministic given rng>

## Tests
- `tests/unit/<module>/…` — <what they cover>
```

## 2. TypeScript (dashboard)

| Area | Rule |
| --- | --- |
| Compiler | `strict: true`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `noImplicitOverride` |
| Lint | ESLint flat config: `typescript-eslint` strict-type-checked, `react-hooks`, `jsx-a11y`, `import/order`; Prettier for formatting |
| Types | Data types come from `src/types/generated/` (made from `schemas/*.schema.json`, incl. `dashboard_slices`, `dashboard_run_index`, `dashboard_cases`, `labels`; R9 X5.3). Never hand-edit them. Use `type` over `interface` except for public props |
| Validation | Every data file is schema-validated at build time; invalid data fails `next build` (one build per fixture set, R9 X1.2). Components receive typed data only |
| Components | Function components, one per file, ≤ 200 lines; server components by default, `"use client"` only when needed |
| State | URL search params for filters (shareable links); no global store |
| Styling | Tailwind with design tokens in `tailwind.config.ts`; no inline colour literals |
| Naming | `PascalCase.tsx` for components, `camelCase.ts` for utilities, `use*` for hooks |
| No computation | Components format and render values from `run.json` / `gate.json`; they never compute metrics or statistics |
| Accessibility | Every chart has a table alternative; colour is never the only signal (icons + text for PASS/WARN/FAIL) |
| i18n | Static de/en dictionaries, route prefix `/de` and `/en`, default `de` (D137); key-parity test; English UI shows German case text verbatim with `lang="de"` on the element |
| Footer | Licence attribution footer on every page (D137) |
| Coverage | `src/lib/**` ≥ 80 % via `vitest --coverage` in `make ui-check` (CLAUDE.md §6) |
| Design | Layout, states, tokens and copy come from `docs/design/ui-spec.md` (D134) |
| CSP | No inline scripts; styles from build-time CSS files; only `report.html` has its own CSP with `style-src 'unsafe-inline'` (R9 X5.2) |
