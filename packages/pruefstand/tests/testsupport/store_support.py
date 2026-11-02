"""Builders for the baseline, sanitising and index tests (T6.1): real models, no fakes."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from testsupport.builders import fixture_f0, make_record, make_run
from testsupport.run_builders import make_case, make_results

from pruefstand.core.ids import CaseId, DocId, TenantId
from pruefstand.core.models.attacks import Canary, CanaryRegistry
from pruefstand.core.models.run import RunArtifacts, RunManifest, RunResults, ScoredCase
from pruefstand.core.models.testcase import TestCase
from pruefstand.store.artifacts import ArtifactStore

FP = "0123456789abcdef"
PREFIX = "CANARY-"


def run_id(index: int) -> str:
    """A valid run id whose sort order follows ``index``."""
    return f"20261102T22{index // 60:02d}{index % 60:02d}-{index:06x}"


def results_for(cases: Sequence[TestCase], **changes: Any) -> RunResults:
    """Results with one record and two metric values per case; manifest fields can be overridden."""
    base = make_results(len(cases))
    values = tuple(
        ScoredCase(case=case, values=scored.values)
        for case, scored in zip(cases, base.values, strict=True)
    )
    records = tuple(
        rec.model_copy(update={"case_id": CaseId(case.id)})
        for case, rec in zip(cases, base.records, strict=True)
    )
    manifest = RunManifest.model_validate(
        {**base.manifest.model_dump(), "n_cases": len(cases), **changes}
    )
    return RunResults(manifest=manifest, records=records, values=values)


def run_of(tmp_path: Path, index: int = 1, count: int = 2, **changes: Any) -> RunArtifacts:
    """A complete run ``run_id(index)`` with fingerprint ``FP`` (override through ``changes``)."""
    fields: dict[str, Any] = {"run_id": run_id(index), "eval_fingerprint": FP, **changes}
    results = results_for([make_case(i) for i in range(count)], **fields)
    return RunArtifacts(results=results, root=tmp_path / "runs" / run_id(index))


def full_cases(*, per_block: int = 2, refusals: int = 2) -> list[TestCase]:
    """The ``full`` split: ``refusals`` cases without a block and ``per_block`` for each block."""
    cases = [
        make_case(
            900 + i,
            split="full",
            category="unanswerable",
            expect_refusal=True,
            gold_doc_ids=[],
            gold_citations=[],
            reference_answer=None,
        )
        for i in range(refusals)
    ]
    for block in range(3):
        cases += [
            make_case(100 * (block + 1) + i, split="full", block=block) for i in range(per_block)
        ]
    return cases


def release_run(tmp_path: Path, **changes: Any) -> RunArtifacts:
    """The release run: all of ``full``, ``block=None``, ``stratum="all"``."""
    cases = full_cases()
    fields: dict[str, Any] = {
        "run_id": run_id(50),
        "eval_fingerprint": FP,
        "splits": ["full"],
        "workload": "nightly",
        **changes,
    }
    return RunArtifacts(results=results_for(cases, **fields), root=tmp_path / "runs" / run_id(50))


def token(name: str) -> str:
    """A synthetic canary token, built at run time."""
    return f"{PREFIX}{name}"


def canary(name: str, tenant: str = "kanzlei_mueller") -> Canary:
    """A token canary named ``name``."""
    return Canary(
        token=token(name),
        tenant=TenantId(tenant),
        doc_id=DocId(f"doc-{name}"),
        kind="token",
        fact=f"Die Freigabe lautet {token(name)}.",
        probe_question=f"Wie lautet die Freigabe {name}?",
        forbidden_answer=token(name),
    )


def registry(*names: str) -> CanaryRegistry:
    """A registry with one token canary per name."""
    return CanaryRegistry(canaries=tuple(canary(n) for n in names))


def gate_run(root: Path, name: str, *, fp: str, **manifest: Any) -> RunArtifacts:
    """A gateable run (fixture F0: 120 cases) named ``name`` under ``root``; not yet written."""
    cases, values = fixture_f0()
    values = {m: v for m, v in values.items() if m != "faithfulness"}
    records = [make_record(c) for c in cases]
    results = make_run(name, cases, values, records=records, eval_fingerprint=fp)
    changed = results.manifest.model_copy(update=manifest)
    return RunArtifacts(results=results.model_copy(update={"manifest": changed}), root=root / name)


def write_gate_run(root: Path, name: str, *, fp: str, **manifest: Any) -> Path:
    """``gate_run`` written into ``root`` through the artifact store; returns the directory."""
    return ArtifactStore(root).write_run(gate_run(root, name, fp=fp, **manifest))
