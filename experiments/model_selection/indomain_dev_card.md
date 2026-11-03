# Data card: indomain_dev.jsonl

Status: **not generated yet.** `indomain_dev.jsonl` is produced by `indomain_cli.py` through GitHub
Models, which the VM cannot reach (every path of `models.github.ai` answers `200 text/plain OK`,
2026-11-03; same from the cloud sandbox). The step runs where the endpoint answers (the owner's
laptop, or an Actions job with `models: read`); `assemble` then overwrites this card with the facts of
the real set. What is already fixed:

| Field | Value |
| --- | --- |
| Purpose | primary ranking set of the embedding benchmark (T3.1b S4): 200 German questions, one gold law passage each; `dev_only` |
| Source text | PUBLIC law text only: the pinned Gesetze-im-Internet archives of `data/sources.yaml` (official works, § 5 UrhG); no private document, canary or held-out text |
| Passage plan | `indomain_dev_sources.json`: 240 planned passages (200 items + 40 reserve), seed 20261103, round-robin over 19 laws, T1.13 slice norms excluded; T4.x excludes and deduplicates all of them |
| Generator | GitHub Models, default `openai/gpt-4.1-mini` (T4.2 pins the datagen model; the choice here is provisional), prompt `indomain_gen_v1`, temperature 0 |
| Spot-check | a model of another provider family (default `meta/Llama-3.3-70B-Instruct`) on the first 30 planned items: answerable from the passage, German, one gold passage; failing items are dropped and replaced from the reserve |
| Record | `id`, `dev_only`, `gold_passage_id`, `law`, `citation`, `passage`, `question`, `evidence_span` + offsets, `reference_answer`, `generator_model`, `checker_model`, `checked` |
