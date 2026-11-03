"""Runs that stop before the first case: a wrong corpus, a judge of the generator's family."""

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from pruefstand.core.errors import CorpusMismatch
from pruefstand.core.logging import get_logger
from pruefstand.core.models.run import RunResults
from pruefstand.core.models.target import TargetInfo
from pruefstand.llm.budget import ChargeTally
from pruefstand.pipeline.plan import Plan, complete_manifest, fingerprint_of_target, store_run
from pruefstand.runner.manifest import RunEnd, RunFacts, build_manifest
from pruefstand.store.artifacts import new_run_id

_log = get_logger(__name__)


def write_aborted_run(plan: Plan, info: TargetInfo | None, out: Path, reason: str) -> Path:
    """Write a run with no cases, ``complete=False``, ``stop_reason="aborted"``, and return it.

    Args:
        plan: The plan of the run.
        info: ``/v1/info`` of the target, or None.
        out: Directory that holds run directories.
        reason: The counter recorded in ``counts`` (for example ``corpus_mismatch``).
    """
    facts = RunFacts(
        run_id=new_run_id(),
        created_at=datetime.now(UTC),
        cases=(),
        target_fingerprint=fingerprint_of_target(plan, info),
        seed=plan.cfg.seed,
        judged_subset=plan.judged_subset,
        judges_given=False,
    )
    end = RunEnd(ChargeTally(), 0.0, Counter({reason: 1}), "aborted", 0)
    manifest = complete_manifest(build_manifest(facts, end, plan.registry), plan, info, "skipped")
    return store_run(out, RunResults(manifest=manifest, records=(), values=()))


def abort_on_corpus_mismatch(plan: Plan, info: TargetInfo | None, out: Path) -> None:
    """Stop before any query when the target serves a corpus the dataset was not built for."""
    if info is None:
        _log.warning("target_info_unavailable", detail="opaque target; corpus version unchecked")
        return
    if info.corpus_version == plan.data.corpus_version:
        return
    directory = write_aborted_run(plan, info, out, "corpus_mismatch")
    msg = (
        f"target serves corpus {info.corpus_version!r}, dataset {plan.data.name} "
        f"{plan.data.version} was built for {plan.data.corpus_version!r}; aborted run {directory}"
    )
    raise CorpusMismatch(msg)
