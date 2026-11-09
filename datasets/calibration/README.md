# Calibration label sets (T5.3, data card)

Label sets that let T5.4 measure how well an LLM judge agrees with known labels, without a German
annotator. Every label comes from an upstream human annotation or is true by construction; no LLM
is used to build them (D860-D868). Builder: `experiments/rq2/build_calibration_sets.py --seed 1234
--out datasets/calibration/v1` (deterministic; the same pins give byte-identical files).

## Sets in `v1/`

| Set | Judged metric | Items | Labels | Hard negatives | Licence / HF config |
| --- | --- | --- | --- | --- | --- |
| `faithfulness_constructed` | `faithfulness` (0-2) | 600 | 300 × 2, 60 × 1, 240 × 0 | 180 (`number_date_swap`, `negation_flip`, `partial_answer`, 60 each) | CC BY-SA 4.0, `germanrag_derived` |
| `correctness` | `answer_correctness` (0-2) | 564 | 282 × 2, 51 × 1, 231 × 0 | 169 (`same_paragraph_span` 51, `number_date_swap` 52, `partial_answer` 51, `negation_flip` 15) | CC BY 4.0, `germanquad_derived` |
| `refusal` | `refusal_judged` (0/1, "is the answer a refusal?") | 600 | 300 × 1, 300 × 0 | 150 `hedged_answer` | CC BY-SA 4.0, `germanrag_derived` |
| `consistency` | `perturbation_consistency` (0/1) | 818 | 449 × 1, 369 × 0 | 83 `number_date_swap` (tagged, not required) | CC BY 4.0, `germanquad_derived` |
| `faithfulness_memerag` (**not here**: `data/derived/memerag_de/`, git-ignored) | `faithfulness` | 391 | 280 × 2, 111 × 0 | 111 `memerag_not_supported` | CC BY-NC 4.0, never published |

Hard negatives per metric: faithfulness 291 (204 in `test`, MEMERAG included), answer_correctness 169
(118 in `test`). `stats.json` has the full counts per set, label, `hard_type`, construction and split.

## Item format

One JSON object per line (`experiments/rq2/calib_schema.py`, `CalibrationItem`): `item_id`,
`metric`, `cluster_id`, `inputs` (exactly the judge prompt variables of `pruefstand.judges.output.SPECS`:
faithfulness `frage, kontext, antwort`; answer_correctness and perturbation_consistency `frage,
referenz, antwort`; refusal_judged `frage, antwort`), `label` (the judge's raw scale), `source`,
`construction`, `calib_split` (`dev` / `test`), and, only when not default, `trivial`,
`hard_negative`, `hard_type`. Load with `CalibrationItem.model_validate_json(line)`.

## Dev/test split (round 13 AI13-12)

Whole `cluster_id`s (GermanQuAD article, GermanRAG positive passage, MEMERAG question) go to `dev`
(30 %) or `test` (70 %), seed 1234, balanced over label x `hard_type` strata. Prompt work and judge
selection use `dev` only; the pass rule and the RQ2 tables use `test`, once per prompt version.

## Limitations

- Constructed labels have no partial credit apart from `partial_answer` (label 1); T5.4 reports binary
  agreement (2 vs < 2) as the primary number.
- Wikipedia-domain sets do not test wrong §, wrong party or wrong period; that is `legal_hard`
  (T5.3 PR 2, after T4.7b, T3.6, T5.1).
- `negation_flip` is rare in `correctness` (15): GermanQuAD answers are mostly short spans without a
  finite verb. `number_date_swap` is the dominant edit in `consistency`.
- Fixed frames (`"Es handelt sich um {a}."`) read awkwardly around full-sentence answers; the label
  (consistent) stays true.
- `unsupported_context` negatives rely on GermanDPR's hard-negative passages not supporting the answer
  (checked only by "the answer string is not in the passage").
- MEMERAG items are the only real model errors; they are few (111 negatives) and stay local
  (CC BY-NC 4.0: no redistribution, no training, no external API).
