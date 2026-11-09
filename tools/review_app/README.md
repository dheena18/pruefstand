# Review tool (T4.7a)

Model review of a built dataset and the owner's 50-item spot-check. Dev-only: it lives in `tools/`
(never under `apps/`), may read `datasets/`, and never writes into `datasets/pruefstand-de/` except
the explicit `apply` step. The owner needs no German: the app shows the source text with the cited
Absatz highlighted and asks two yes/no questions.

## Workflow

```text
make dataset      BUILD=dataset.yaml   # pruefstand build-dataset (resumable stages)
make review-model BUILD=dataset.yaml   # model review (local reviewer; on the VM: pruefstand-lock make review-model ...)
make review-app   BUILD=dataset.yaml   # spot-check on http://localhost:8501 (bound to 127.0.0.1; on the VM: ssh -L 8501:127.0.0.1:8501 <vm>)
make review-summary BUILD=dataset.yaml # error rate per stratum, owner flag rates, trust verdict
make review-apply BUILD=dataset.yaml   # decisions into the dataset directory + ReviewRound entries
```

`BUILD` is the dataset config (`dataset.yaml`; the slice build is
`packages/pruefstand/tests/fixtures/dataset_small.yaml`). All review files are in
`datasets/_work/<name>-<version>/review/` (git-ignored):

| File | Content |
| --- | --- |
| `sample.jsonl` | ids of the cases the model reviewed: 100 % of `smoke`, `core` and all attack/probe cases, a seeded 20 % of the rest (at least 30 per category) |
| `items.jsonl` | one `ReviewItem` per reviewed case: verdict `ok`/`fix`/`reject`, reason, deterministic findings; written as they arrive, so an interrupted run continues |
| `spotcheck_sample.jsonl` | the 50 ids for the owner: all `smoke` items first, then a stratified draw of model-`ok` and model-`fix` items |
| `spotcheck_decisions.jsonl` | `case_id, citation_ok, plausible, note, reviewer, ts` (written by the app) |

## The app

One item per screen. Left: question, reference answer, gold citation, the model's verdict. Right:
the chunks of the cited provision, the cited Absatz on a yellow background and the evidence
sentence in a stronger yellow; a wrong citation shows the text unmarked. Enter a pseudonym in the
sidebar (stored as `owner-spotcheck:<pseudonym>`), then answer with the buttons or the keys
`y` / `n`: first "does the citation point to the right section and paragraph?", then "is the answer
plausible given the highlighted text (numbers, dates, durations)?". An optional note is saved with
the decision. The app takes the config from `REVIEW_APP_CONFIG` (`make review-app` sets it).

## Rules the tool implements

- The reviewer is reject-only (ADR-0019, D330): a `fix` may change the question, never the reference answer.
- Deterministic checks win over the model: gold citation vs chunk key, copy rules for a fixed
  question, no fix for an unanswerable case (D750).
- `reject` removes the case and its whole cluster from every split; a stratum above 10 % errors needs regeneration.
- Trust rule: if the owner flags more than 10 % of the spot-checked model-`ok` items, the model
  review is not trusted: write `review_item_de_v<N+1>.txt`, re-run the model review on the same
  sample and spot-check again (D751).

## Tests

`tools/review_app/tests/` runs the app with Streamlit's `AppTest` on three real slice items. The
model review is tested against real answers of the A40 judge recorded by
`pruefstand-lock bash scripts/models/record_cassettes.sh --review`.
