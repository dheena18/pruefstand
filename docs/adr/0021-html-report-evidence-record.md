# 0021 — HTML report and release evidence record

- Status: Accepted
- Date: 2026-11-03
- Tasks: T6.4 (also read by T8.1, T10.2)
- Amends: `docs/architecture/interfaces.md` §10 (`EvidenceRecord`), §15 (`pruefstand report --config`), `data-model.md` §1.1

## Context
T6.4 adds the single-file `report.html` (ui-spec §13) and the release evidence record. `render_html` and
`build_evidence_record` are fixed by interfaces §10 (`base` optional). Two things were not specified:
the fields of `EvidenceRecord`, and where the artefact hashes and the gate thresholds come from, because
neither `GateReport` nor `RunManifest` carries the policy and `build_evidence_record` only receives manifests.

## Decision
1. `EvidenceRecord` (`core.models.evidence`, schema `evidence_record`) holds the decision, dataset and corpus
   versions, fingerprints, config hash, both runs as `EvidenceRun`, model and judge ids, prompt and metric
   versions, `thresholds: GatePolicy | None`, per-metric `EvidenceMetric` results (means, CI, p, MDE, max_drop,
   max_value, table of ui-spec §11.1) and `EvidenceSecurity`. The exact field list is in interfaces §10.
2. The builder is pure and leaves the three SHA-256 hashes (both `run.json`, candidate `gate.json`) and
   `thresholds` empty. `pruefstand report --format evidence --config <yaml>` fills them with `model_copy`;
   the flag is new and required for `evidence` (exit 2 when missing, or when `stable_hash(cfg)` differs from
   `RunManifest.config_hash`, the function `pipeline/run.py` uses).
3. `html` and `evidence` write `report.html` / `evidence.json` into the run directory (atomic rename) and print
   the path. They are the full private render; the public copy is rendered from `sanitise_run` output by T8.1.
4. Safety: all untrusted text is cleaned (`mask_canaries` folding, control/bidi removal, caps) and escaped by
   Jinja autoescape. Canary masks read `‹masked›`. The report's CSP is a `<meta>` with the hash of the one inline
   script, computed at render time.

## Alternatives considered
| Option | Why not |
| --- | --- |
| Read the policy from `RunManifest` | not stored there; adding it would change `config_hash`-relevant models |
| Hash files inside `build_evidence_record` | it would need paths and I/O; interfaces §10 gives it manifests only |
| Reuse the PR comment's `md_escape` for HTML | it escapes Markdown, so the report would show backslashes |

## Consequences
- Positive: one rule for table membership (`assign_block`), one masking function for comment and report.
- Negative / cost: `_tokens.css` and `_licences.json` are hand copies until T8.1 generates them.
- Follow-ups: `--reviewer` flag for `pruefstand report` (the field exists, the CLI passes `None`); T8.1 drift checks.
