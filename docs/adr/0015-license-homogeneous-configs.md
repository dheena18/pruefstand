# 0015 — Dataset split into license-homogeneous configs

- Status: Accepted (revised 2026-10-28: licences re-checked on the HF cards; MEMERAG added; revised 2026-10-31: per-checkpoint model licences; round 9 X3.1, X3.8, X3.12; round 11 AI11-08, AI11-12)
- Date: 2026-10-27
- Tasks: T2.1, T4.1, T4.7b, T5.3, T9.1b

## Context
The sources carry different licences:
- official works, public domain under § 5 UrhG (Gesetze im Internet);
- EUR-Lex, reuse with attribution and change notice (Commission Decision 2011/833/EU);
- GermanQuAD and GermanDPR, **CC BY 4.0** per their HF cards (checked 2026-10-28; the v1 spec said
  CC BY-SA); GermanRAG, CC BY 4.0 per its card, re-verified in T2.1;
- the Open Legal Data collection, ODbL v1.0 (share-alike for databases);
- MEMERAG (German subset, used for faithfulness-judge calibration), **CC BY-NC 4.0**, with the
  request that the data not be used to train models.

Mixing them in one dataset blurs who gets credited for what; ODbL's share-alike cannot be combined
with another share-alike licence, and NC data must not enter a dataset that others may use commercially.

## Decision
HF dataset `<HF_USER>/pruefstand-de` with these configs:

| Config | Contents | Licence |
| --- | --- | --- |
| `laws_eurlex` | cases built from GII laws + EUR-Lex | CC BY 4.0 (source credited, changes marked) |
| `germanquad_derived` | cases and refusals from GermanQuAD/DPR | CC BY 4.0 |
| `germanrag_derived` | cases and refusals from GermanRAG | CC BY-SA 4.0 (inherited from GermanDPR per its README; owner decision, T2.1) |
| `oldp_derived` | cases built from OLDP decisions | ODbL 1.0 |
| `own` | planted attacks, canary probes, synthetic docs | CC BY 4.0 |

- Every `TestCase` carries `license_config`; `validate_dataset` fails on any file that mixes licences.
  A case whose sources would need ODbL plus another share-alike licence is dropped.
- **MEMERAG is never redistributed**: no config, no item text in any artefact (dataset, dashboard,
  report, repo). A download script fetches it at a pinned commit for T5.3/T5.4; only aggregate
  agreement numbers are published, with attribution.
- `data/download.py` (T2.1) compares each HF card's licence field with
  `DATA_LICENSES.md` and fails on a mismatch.
- Public artefacts outside the HF dataset (dashboard data, demo index, PR comments) carry the
  attribution notices too (`DATA_LICENSES.md` §4).
- LLM-generated dataset text records the generating **checkpoint** and its output terms in the dataset
  card; licences are checked per checkpoint, not per family (`DATA_LICENSES.md` §5). Datagen uses the
  pinned GitHub Models datagen model for public text (SPEC §6.3, ADR-0019; its output terms are checked before
  publishing) with its attribution; Qwen2.5-3B and Qwen2.5-72B are excluded. The gating judge `gemma3:12b`
  reviews in reject-only mode and never writes reference text (SPEC §3.5, AI11-12). Synthetic private documents
  are drafted locally by the judge model (so the dataset card also carries the Gemma notice), never by a `qwen`
  model and never by an external provider. `legal_hard` (built in T5.3) consists of A40 generator answers (the
  pinned tier-2 `qwen` generator, `qwen3.8:27b-q8_0` if its licence verifies, else a named Qwen3
  fallback, Apache-2.0, **verify**) edited deterministically. It is publishable under `own` **only if**
  T0.6 C3 finds an allowlisted licence for that checkpoint; otherwise it stays local like MEMERAG
  (calibration only, aggregate numbers published; AI11-08, `DATA_LICENSES.md` §5).

## Alternatives considered
| Option | Why not |
| --- | --- |
| One config, one licence | Wrong for the ODbL parts and over-restricts our own data |
| Include MEMERAG items in the dataset | CC BY-NC + "do not train" request; would make the dataset non-commercial |
| Leave out the GermanQuAD family | Loses the human gold answers used for calibration |

## Consequences
- Positive: attribution is clean; users can pick only the permissive subsets; licence drift on
  upstream cards is caught in CI.
- Negative: loaders concatenate configs; split sizes are reported per config; reproducing the
  calibration needs the separate MEMERAG download.
