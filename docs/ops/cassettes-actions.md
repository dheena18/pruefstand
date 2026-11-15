# Datagen recordings on the VM CPU model

GitHub Models was retired on 2026-07-30 (`models.github.ai` answers `200 text/plain` for every path, D604), so the
`cassettes-models.yml` workflow is gone (D1202). Public-text datagen now runs on an **on-demand CPU model on the VM**
(D1200, D1201): an official Mistral GGUF (Ministral 3 Instruct 2512, Q4_K_M, Apache-2.0, family `mistral`) served by
the pinned llama.cpp `llama-server`, started by `scripts/models/vm_llm.sh` as the owner user.

| Target | What it records | Command (VM, model started) |
| --- | --- | --- |
| `indomain_dev` | `indomain_dev.jsonl` (T3.1b S4): questions for the 240 planned public law passages | `PYTHONPATH=experiments uv run python -m model_selection.indomain_cli generate --max-calls N --retries 2` |
| T4.2 | datagen cassettes (real chunks of the committed slice corpus) | `bash scripts/models/record_cassettes.sh --dataset` |
| T4.5 | rewrite cassettes (VM model) and equivalence checks (A40 judge) | `pruefstand-lock bash scripts/models/record_cassettes.sh --perturb` (lead: the judge is on the cluster) |

## Start, use, stop

```bash
bash scripts/models/vm_llm.sh start          # 14b (default) or: start 8b; prints the URL
export PRUEFSTAND_JUDGE_BASE_URL=http://127.0.0.1:18091/v1   # the URL it printed
export PRUEFSTAND_DATAGEN_BACKEND=vm         # the default; `github` only for old GitHub Models ledgers
# ... the commands above ...
bash scripts/models/vm_llm.sh stop           # always, also after a failure
```

Rules the launcher enforces (D1200): bound to `127.0.0.1` only (never reachable from `gate-net` or another host,
D850), 16 threads pinned to CPUs 0-19 (`VM_LLM_THREADS` at most 80 = half the vCPUs, `VM_LLM_CPUS`), `nice 15` and
`ionice` idle, a hard stop after `VM_LLM_MAX_MIN` (240) minutes, the model file's size and SHA-256 checked. It holds
`gpu.lock` (`pruefstand-lock`) **and** every `make check-vm` slot for its whole life: it refuses to start (exit 75)
while a gate run or a check runs, and a gate job or a check waits until it is stopped. So stop it as soon as the
batch is done.

Every client checks that the server at `PRUEFSTAND_JUDGE_BASE_URL` serves the pinned alias before it sends anything
(`generate_qa_clients.check_vm_served`, `indomain_gen.call_vm`), so a batch never lands on the tier-1 llama.cpp
model by mistake.

## Invalid answers: constrained JSON and regeneration (D1201)

The benchmark (D1200) found 35-45 % of first in-domain answers invalid: JSON wrapped in code fences, evidence spans
over 400 characters or not copied verbatim. `indomain_gen` therefore asks the VM model with `response_format`
json_schema (`GEN_SCHEMA`: the three fields, span 20..400 characters; fenced answers are still parsed), and
`indomain_cli generate --retries N` (default 2) asks an invalid item again up to N more times. Every attempt is one
call against `--max-calls` and is cached as `<passage id>#retry<k>`; the summary line reports calls, retries and
items left invalid after N retries ("exhausted"). The reserve passages of the plan (40) replace exhausted items in
`assemble`.

## What stays as before

- **Public text only.** The inputs are the pinned GII law texts, the committed slice corpus and the pilot questions.
  `generate_qa` skips private and attack chunks itself. The VM model is local (`openai_compatible_local`), so
  nothing leaves the VM; private docs and canaries still use the local judge model `gemma3:12b` (D330), unchanged.
- **Second family.** The VM has only the `mistral` family. The T4.5 equivalence judge is the A40 judge
  (`PRUEFSTAND_PERTURB_JUDGE_MODEL=ollama/gemma3:12b`, run by the lead under `pruefstand-lock`). The two other
  second-family steps have **no working backend** now that GitHub Models is gone: `indomain_cli check` (the
  spot-check of the first 30 items, needed by `assemble`) and `generate_qa --cross-check` (off by default; the
  pass-2 local judge stays the independent check). Both are a follow-up (an Ollama path for the checker).
- **Cache.** In-domain answers stay in `data/raw/indomain_dev_cache` (git-ignored); the model id is part of the
  key, so VM and GitHub answers never mix and a stopped batch resumes where it stopped.

## Throughput (D1200, measured 2026-11-15 on the VM, 16 threads on CPUs 0-19)

14B (default): about 67 s per in-domain generation call, 13 of 20 first answers valid; 8B: 58 s, 11 of 20 (D1200).
Both cost about 5.7 h of server time per 200 valid items before retries; run them in batches (`--max-calls`),
outside the night window and never during a gate run.
