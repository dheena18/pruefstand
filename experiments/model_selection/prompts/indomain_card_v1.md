# Data card: indomain_dev.jsonl

Status: generated. {n} German questions, each with one gold passage of PUBLIC law text. Every
record carries `"dev_only": true`: the set ranks embedding models (T3.1b S4) and must not be used
as a test set. T4.x excludes and deduplicates every passage listed in `indomain_dev_sources.json`
(`source_passage_ids`: items and reserve) from all splits.

| Field | Value |
| --- | --- |
| Source text | Gesetze im Internet, pinned archives of `data/sources.yaml` (SHA-256 in the sources file); official works, § 5 UrhG, see `DATA_LICENSES.md` |
| Gold passage | one whole norm; `gold_passage_id` is the `doc_id` (e.g. `gii-bgb-622`); `evidence_start` and `evidence_end` are character offsets of the verbatim `evidence_span` in `passage` |
| Generator | `{gen}` via GitHub Models, prompt `{gen_prompt}`, temperature 0 |
| Spot-check | `{check}` (another provider family), prompt `{check_prompt}`, first {n_check} planned items, verdicts in `indomain_dev_checks.jsonl`: {checked} checked, {dropped_check} dropped and replaced from the reserve |
| Automatic rules | question 25-300 characters, ends with `?`, German, no reference to "the text", evidence span verbatim (20-400 characters), answer 10-600 characters; {dropped_no_item} planned passages had no valid item |
| Selection | seed {seed}, round-robin over the laws, norms of {min_chars}-{max_chars} characters, T1.13 slice norms excluded |
| Private data | none: no private document, canary or held-out text was used or sent |
| Output terms | model output under the GitHub Models terms (verify before any redistribution outside this repository) |

Items per law:

| Law | Items |
| --- | --- |
{laws}
