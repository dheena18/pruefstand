# Data licenses

Code in this repository is MIT-licensed (`LICENSE`). Data is **not** committed (except the small
hand-written fixtures in `datasets/fixtures/`, CC BY 4.0). This file lists every external source,
its licence, the attribution text we use, and which Hugging Face config of
`<HF_USER>/pruefstand-de` derived data goes to. Adding a source means adding a row here in the same PR.

This is not legal advice. Re-check each source's terms when the pinned version changes.

## 1. Sources

| Source | Pinned version (see `data/sources.yaml`) | Licence | HF config for derived data | Redistribution |
| --- | --- | --- | --- | --- |
| Gesetze im Internet (BMJ / juris) | download date + SHA-256 per `xml.zip` | Official works, not protected by copyright (§ 5 Abs. 1 UrhG) | `laws_eurlex` | Allowed; we still credit the source |
| Open Legal Data – court decisions (`openlegaldata/court-decisions-germany`) | config `dump-20260520` / `-1k`, HF revision SHA | ODbL v1.0 (database); decision texts are public-domain official works | `oldp_derived` | Derived database must be shared under ODbL with attribution |
| Open Legal Data – laws (`openlegaldata/laws-germany`) | HF revision SHA | ODbL v1.0 | `oldp_derived` | Same |
| Open Legal Data – citation graph (`openlegaldata/legal-citation-graph-germany`) | HF revision SHA | ODbL v1.0 | `oldp_derived` | Same |
| EUR-Lex (Publications Office of the EU) | CELEX ids + retrieval date + SHA-256 | Reuse under the EUR-Lex legal notice and Commission Decision 2011/833/EU (credit the source, indicate changes; consolidated texts are not authentic) | `laws_eurlex` | Allowed with credit and change notice |
| GermanQuAD (deepset) | HF revision SHA | CC BY 4.0 (HF card `deepset/germanquad`, checked 2026-10-28) | `germanquad_derived` | Allowed with attribution and change notice |
| GermanDPR (deepset) | HF revision SHA | CC BY 4.0 (HF card `deepset/germandpr`, checked 2026-10-28) | `germanquad_derived` | Allowed with attribution |
| GermanRAG (DiscoResearch) | HF revision SHA | Card metadata says CC BY 4.0, but the README says the derived work inherits CC BY-SA 4.0 from GermanDPR → **CC BY-SA 4.0** (owner decision, T2.1, section 7) | `germanrag_derived` (own config) | Allowed with attribution |
| MEMERAG (`amazon-science/MEMERAG`), German subset | repo commit SHA | **CC BY-NC 4.0** (LICENSE file, checked 2026-10-28); README: data should not be used to train models | **none** — calibration only (T5.3/T5.4) | **Never redistributed**: download script only; no item text in the HF dataset, dashboard, report or repo; publish only aggregate agreement numbers with attribution; never used for training or fine-tuning |
| GerDaLIR (`lavis-nlp/GerDaLIR`, `mteb/GerDaLIR`) | repo commit / HF revision | See upstream repo; built from Open Legal Data | not redistributed (used for model selection only) | Do not redistribute until licence verified |
| deepset/prompt-injections | HF revision SHA | Apache 2.0 | `own` (as seed strings inside planted attacks) | Allowed with licence notice |
| deepset/deberta-v3-base-injection (model) | HF revision SHA | see model card | — (model, not data) | Not redistributed |
| BSI IT-Grundschutz (optional) | edition + date | **Verify before use** (one secondary source reports CC BY-SA 4.0 for the OSCAL edition; not confirmed) | not used until verified | Do not redistribute until verified |
| Own synthetic private docs, canaries, planted attacks, fixtures | dataset version | CC BY 4.0 (data), MIT (generator code) | `own` | Allowed |
| `legal_hard` calibration set (T5.3): A40 generator answers on `full` + deterministic edits (party/section swap, sentence drop, unsupported append) | dataset version | CC BY 4.0 (our edits and labels); generator output terms per §5 (the pinned tier-2 `qwen` generator) | `own` **only if** T0.6 C3 finds an allowlisted licence for the generator checkpoint (round 11 AI11-08); else none | Allowed only under that condition; otherwise `legal_hard` stays **local** like MEMERAG (calibration only, aggregate numbers in the report). Source law text keeps its `laws_eurlex` credit |

## 2. Hugging Face configs

| Config | Licence | Contains |
| --- | --- | --- |
| `laws_eurlex` | CC BY 4.0 | Test cases generated from Gesetze im Internet and EUR-Lex |
| `oldp_derived` | ODbL v1.0 | Test cases generated from Open Legal Data decisions/laws/citation graph |
| `germanquad_derived` | CC BY 4.0 | Cases and labels derived from GermanQuAD, GermanDPR |
| `germanrag_derived` | CC BY-SA 4.0 | Cases and labels derived from GermanRAG; never combined with another config's material |
| `own` | CC BY 4.0 | Planted attacks, canary/leak probes, filter-bypass and system-prompt probes, synthetic private docs |

Every `TestCase` has exactly one `license_config`. `pruefstand validate dataset` fails if a case's
sources would require a different config (e.g. a multi-hop case mixing OLDP and GermanQuAD text).
ODbL is never combined with another share-alike licence (e.g. CC BY-SA) in one config or derived
artefact: there is no "most restrictive" common licence, so a case that would need both is
**dropped**. CC BY-NC material (MEMERAG) never enters any released artefact.
`scripts/data/check_licenses.py` (T2.1) reads each HF card's licence field and fails CI when it
differs from this file.

## 3. Attribution texts (used in dataset card, report and README)

- **Gesetze im Internet:** "Gesetzestexte: Bundesministerium der Justiz / juris GmbH,
  www.gesetze-im-internet.de. Amtliche Werke gemäß § 5 UrhG."
  Test fixtures `packages/pruefstand/tests/fixtures/gii/*.xml` (T2.2) are byte-exact excerpts of single
  `<norm>` elements (BGB, KSchG, ArbZG, AktG, EGBGB, KWG) of the pinned files, trimmed only by dropping
  norms. Basis: official works, § 5 Abs. 1 UrhG; they carry the attribution above (see the README there).
- **Open Legal Data:** "Contains information from Open Legal Data (openlegaldata.io), made available
  under the Open Database License (ODbL) v1.0."
  Confirmed in T2.3: the text is identical to `attribution` of the three `oldp_*` sources in `data/sources.yaml`;
  every `Document` and `Chunk` of the loader carries `license="ODbL-1.0"` (collection; the individual decisions are
  official works, § 5 UrhG, see the section 7 override). Test fixtures `packages/pruefstand/tests/fixtures/oldp/*.json`
  and `oldp_graph/edges.jsonl` (T2.3) are three real records and five edges of the pinned `-1k` sample, trimmed; they
  carry this attribution and stay in the OLDP-only `oldp_derived` scope (ODbL data is never mixed into another config).
- **EUR-Lex:** "Source: EUR-Lex, © European Union, https://eur-lex.europa.eu. Reuse authorised under
  the EUR-Lex legal notice and Commission Decision 2011/833/EU. Consolidated versions are not
  authentic. The content has been modified (chunked, questions generated)."
- **GermanQuAD / GermanDPR:** "GermanQuAD and GermanDPR by deepset (Möller, Risch, Pietsch, 2021),
  CC BY 4.0, https://deepset.ai/germanquad. Modified."
- **GermanRAG:** "GermanRAG by DiscoResearch, based on GermanDPR, CC BY-SA 4.0 (inherited). Modified."
- **MEMERAG (report only, aggregate numbers):** "Faithfulness labels from MEMERAG (Cruz Blandón et al.,
  ACL 2025), CC BY-NC 4.0, https://github.com/amazon-science/MEMERAG. Used for evaluation only."
- **deepset/prompt-injections:** "deepset/prompt-injections, Apache License 2.0. Strings embedded in
  synthetic documents."

## 4. Rules

1. Raw corpora, model weights and HF downloads go to `data/raw/` (git-ignored; checksums in
   `data/raw/MANIFEST.json`), never to Git.
2. Download scripts pin a version (dump date, HF revision, CELEX + date) and verify SHA-256.
3. Derived data inherits the licence of its single licence family (CC BY 4.0, or ODbL for OLDP);
   artefacts that would mix ODbL with another share-alike licence are not produced; NC data is never released.
4. No real personal data. Synthetic private documents use invented names and companies, checked
   against the public corpus at planting time.
5. The dataset card lists every config, licence and attribution text above.
6. **Public artefacts other than the HF dataset** also redistribute data: dashboard data, the demo's
   Qdrant index and public PR comments. They carry the attribution notice of every source they show.
   The demo index contains OLDP-derived text and is a "Publicly Used" derivative database under ODbL:
   the demo page shows the ODbL notice and links to the `oldp_derived` config as the offered database.
   Full run artefacts with chunk text and the baselines stay in the private executor repo (ADR-0004).
7. **Canaries:** the public canary set is rotated every dataset release (`canaries/retired.json`);
   the held-out set is never published anywhere.

## 5. Generated text and model output terms

Dataset text written by an LLM (questions, answers, private docs, perturbations) is listed in the
dataset card with the generator model and its output terms. Licences are checked **per checkpoint**,
never per family: checkpoints of one family carry different licences (e.g. some Qwen checkpoints are
Apache-2.0, others are under the Qwen or Qwen Research licence). The family plan (SPEC §6.3, ADR-0019) fixes
datagen to a pinned GitHub Models free-tier model of a family that is neither `qwen` nor `gemma` (public text only;
pinned in T4.2) and, for private docs, canaries and held-out data, the local judge model `gemma3:12b`. Check before each release (**verify**
every row on the pinning day against the model card):

| Checkpoint (role) | Licence / output terms to check | Default for published data |
| --- | --- | --- |
| GitHub Models datagen model (pinned in T4.2; family ≠ `qwen`, ≠ `gemma`; questions, references, perturbation rewrites of **public** text, `legal_hard` review; ADR-0019) | GitHub Models terms **and** the model's own output terms (**verify** on the pinning day: may outputs be published in a dataset, attribution or naming duties, restrictions on training other models) | **allowed** as the pinned datagen entry only if its terms permit publishing the outputs, with the attribution in the dataset card; otherwise pick another GitHub Models model (T4.2 S0) |
| Gemma-3-12B-it as `gemma3:12b` (the one judge for PR and nightly; reject-only reviewer of every split; local writer of private docs, canaries and held-out data, ADR-0019); Gemma-3-4B-it (RQ2 size contrast only) | Gemma Terms of Use + Gemma Prohibited Use Policy (**verify**: use restrictions pass through to users of the model, notice duties, whether generated private docs or judge verdicts count as "Model Derivatives" or outputs) | allowed with the Gemma notice in NOTICE / the dataset card; it **never writes or rewrites reference text** (a `fix` may change only a question); the synthetic private docs it drafts are human-reviewed and published only as listed in the dataset card with the Gemma terms; judge verdicts are not published as data |
| `qwen3.8:27b-q8_0` (tier-2 generator, Ollama tag already on the cluster; round 10 Z3) | **verify** with `ollama show` (T0.6 C3): base model, licence text and family; pinned only if family `qwen` and the licence is on the allowlist, else an official Qwen3 tag replaces it | outputs published **only** inside `legal_hard`; allowed iff T0.6 C3 (`ollama show --license`, `ollama show --modelfile` `FROM` line, registry probe) finds an allowlisted licence, else `legal_hard` stays local like MEMERAG (AI11-08). Not used for any other data generation |
| Qwen2.5-1.5B-Instruct, Qwen3-1.7B / 4B / 8B / 14B (generator, tier 1 / M11 / fallback, never datagen) | Apache-2.0 (**verify** per checkpoint) | not used for data generation (generator family) |
| Qwen2.5-3B-Instruct | Qwen Research licence, non-commercial (**verify**) | **excluded** |
| Qwen2.5-72B-Instruct | Qwen licence (**verify**) | **excluded** |
| GitHub Models (free tier: tier-1 judge, second-family cross-checks, RQ2 judge arms) | GitHub Models terms (publishing outputs, **verify**) | public items only (cases whose inputs contain a registered canary are excluded before selection); never published as data |
| Other free tiers (Mistral, Gemini, Groq, OpenRouter `:free`) | provider terms; free tiers may train on inputs | not used for data generation; never sent private docs or canaries |

## 6. Models used (not redistributed)

Model weights are never committed or redistributed; they are downloaded at pinned revisions with
SHA-256 (Hugging Face) or pulled as Ollama tags pinned by manifest digest into the cluster's model store
`/data/dheena/Models` (ADR-0019). An Ollama tag is checked against the licence of the checkpoint it was
converted from (`ollama show --license`); GGUF quantisation does not change the licence. A tag that
cannot be re-pulled from the registry (built locally or from a user namespace; T0.6 C3) is copied once with
its manifest over SSH to the VM data root `backups/models/`, digest-checked (AI11-08). No model under a non-commercial licence (e.g. CC BY-NC) is used in any default profile;
`test_catalogue.py` checks each catalogue entry's `license` field against an allowlist. Rerankers and
embeddings (licences **verify**): `BAAI/bge-m3` (MIT; served as the Ollama `bge-m3` tag), `intfloat/multilingual-e5-small` / `-large`
(MIT), `BAAI/bge-reranker-v2-m3` (Apache-2.0), `Alibaba-NLP/gte-multilingual-reranker-base`
(Apache-2.0), `jinaai/jina-embeddings-v2-base-de` (Apache-2.0, optional). Rejected:
`jinaai/jina-reranker-v2-base-multilingual` and jina-embeddings-v3 (CC BY-NC 4.0).

**Tokenizers (round 13, AI13-05).** Every catalogue chat entry carries `tokenizer: {source, sha256}`; the
generator's tokenizer is baked into the rag-demo image next to `bge-m3`'s so prompt budgets are counted with
the right vocabulary. Tokenizer files follow the licence of their model: Qwen from its HF repo
(Apache-2.0, **verify**); Gemma's HF tokenizer is behind the Gemma Terms gate, so it is used only after the owner
accepts those terms (`[HUMAN]`), or it is extracted from the pinned GGUF's vocabulary with the `gguf` reader,
which carries the same Gemma Terms. Tokenizer files are never redistributed outside the images that use them.

**`rq1` split (round 13 P3.2).** The RQ1 robustness set (`Split.RQ1`) is built from the same sources and
`license_config` rules as `full`; it is used offline in `experiments/` and, like every split, released only
under the config of its sources.

## 7. Pinned sources (T2.1, checked 2026-10-31)

`data/sources.yaml` is the source of truth for pins; `data/download.py` reads each Hugging Face
card's `license` field (and the `LICENSE` file of the GitHub source) and exits 3 (`LicenseMismatch`)
when it differs from the `license` there. This check lives in `data/download.py`, not in a separate
`scripts/data/check_licenses.py`.

| Source id | `license` in `sources.yaml` | `license_config` | Redistribute | Local path |
| --- | --- | --- | --- | --- |
| `gii:<abbrev>` (30 laws) | `official-work-5-urhg` | `laws_eurlex` | yes | `data/raw/gii/<abbrev>/xml.zip` |
| `eurlex:<celex>` (20 acts, DE + EN; fetched from the Publications Office CELLAR) | `eurlex-legal-notice` | `laws_eurlex` | yes | `data/raw/eurlex/<celex>/{de,en}.html` |
| `oldp_decisions` | `odbl` (card has no `license` field: documented override, below) | `oldp_derived` | yes, under ODbL | `data/raw/hf/oldp_decisions/` |
| `oldp_laws`, `oldp_citation_graph` | `odbl` (card agrees) | `oldp_derived` | yes, under ODbL | `data/raw/hf/<id>/` |
| `germanquad`, `germandpr` | `cc-by-4.0` (card agrees) | `germanquad_derived` | yes | `data/raw/hf/<id>/` |
| `germanrag` | `cc-by-sa-4.0` (card metadata says cc-by-4.0: documented override, below) | `germanrag_derived` | yes, under CC BY-SA | `data/raw/hf/germanrag/` |
| `prompt_injections` | `apache-2.0` (card agrees) | `own` | yes, with notice | `data/raw/hf/prompt_injections/` |
| `memerag` | `cc-by-nc-4.0` (LICENSE file agrees) | `download_only` | **no** | `data/raw/github/memerag/` |

Documented overrides of the card check (`card_license` in `sources.yaml`; the card must say exactly
that value, anything else exits 3). These are owner decisions of 2026-10-31, not generic bypasses:

* `openlegaldata/court-decisions-germany`: the card has no `license` field (`card_license: none`). We
  record **ODbL v1.0 for the collection and para 5 UrhG (official works) for the individual decisions**.
* `DiscoResearch/germanrag`: the card metadata says `cc-by-4.0` (`card_license: cc-by-4.0`) but its README
  says the derived work inherits **CC BY-SA 4.0** from GermanDPR; we use the stricter reading. GermanRAG
  therefore has its own config `germanrag_derived`; `load_sources` fails if any config mixes CC BY, CC BY-SA
  and ODbL sources.
