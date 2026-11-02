"""Builders for the report tests (T1.9): ``GateReport`` / ``SliceDecision`` and the S5 scenarios.

A ``GateReport`` carries numbers only, so the scenarios construct it directly (like the tests of the
gate's own decision logic); the manifests come from ``testsupport.run_builders.make_manifest``.
"""

from typing import Any

from testsupport.run_builders import make_manifest

from pruefstand.core.enums import GateStatus
from pruefstand.core.ids import CaseId
from pruefstand.core.models.gate import BootstrapResult, GateReport, HardFailFinding, SliceDecision
from pruefstand.core.models.run import CostSummary, RunManifest

PASS, WARN, FAIL = GateStatus.PASS, GateStatus.WARN, GateStatus.FAIL
INSUFFICIENT = GateStatus.INSUFFICIENT_DATA
BASE_SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
CAND_SHA = "d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8091a2b3c4d"
Scenario = tuple[GateReport, RunManifest | None, RunManifest]


def bootstrap(diff: float, low: float, high: float, *, n_clusters: int = 40) -> BootstrapResult:
    """Return a bootstrap result with the given interval."""
    return BootstrapResult(
        mean_diff=diff,
        ci_low=low,
        ci_high=high,
        p_value=0.01,
        method="bootstrap",
        se=0.02,
        n_cases=n_clusters + 10,
        n_clusters=n_clusters,
        n_resamples=2000,
        confidence=0.95,
    )


def decision(  # noqa: PLR0913  (test builder; every field is a keyword)
    metric: str = "context_recall",
    *,
    dimension: str = "overall",
    value: str = "overall",
    status: GateStatus = FAIL,
    gated: bool = True,
    base: float = 0.86,
    cand: float = 0.79,
    ci: tuple[float, float, float] | None = (-0.07, -0.10, -0.04),
    mde: float | None = 0.04,
    max_drop: float | None = 0.05,
    max_value: float | None = None,
    reason: str | None = None,
    notable: bool = False,
    n_clusters: int | None = 40,
) -> SliceDecision:
    """Return one ``SliceDecision`` (defaults: the FAIL ``context_recall`` overall row)."""
    return SliceDecision(
        metric=metric,
        dimension=dimension,
        value=value,
        status=status,
        gated=gated,
        notable=notable,
        baseline_mean=base,
        candidate_mean=cand,
        result=None if ci is None else bootstrap(*ci),
        p_adjusted=None,
        mde=mde,
        max_drop=max_drop,
        max_value=max_value,
        n_clusters=n_clusters,
        informational_reason=reason,
    )


def hard_fail(case: str = "law-0107", metric: str = "canary_leak") -> HardFailFinding:
    """Return one redacted hard-fail finding."""
    return HardFailFinding(
        rule="hard_fail", case_id=CaseId(case), metric=metric, evidence="… CANARY-**-****** …"
    )


def gate_report(**changes: Any) -> GateReport:
    """Return the FAIL report (one gated FAIL, one hard fail); keyword arguments override fields."""
    data: dict[str, Any] = {
        "schema_version": "1",
        "status": FAIL,
        "baseline_run_id": "20261101T220000-ba5e00",
        "candidate_run_id": "20261102T220000-ab12cd",
        "eval_fingerprint": "e" * 16,
        "hard_fails": (hard_fail(),),
        "decisions": (decision(),),
        "absolute_checks": (),
        "notable_slices": (),
        "likely_cause": None,
        "top_failing_cases": ("law-0042", "law-0107"),
    }
    return GateReport.model_validate({**data, **changes})


def manifest(**changes: Any) -> RunManifest:
    """Return a tier-2 (``a40``) candidate manifest; keyword arguments override fields."""
    data: dict[str, Any] = {
        "run_id": "20261102T220000-ab12cd",
        "git_sha": CAND_SHA,
        "git_ref": "feature/x",
        "pr_number": 42,
        "stack": "a40",
        "splits": ["core", "robust_pr"],
        "n_cases": 790,
        "duration_s": 1092.0,
        "cost": CostSummary(
            usd=0,
            prompt_tokens=4_000_000,
            completion_tokens=100_000,
            gpu_seconds=2100.4,
            llm_calls=10,
        ),
        "judge_mode": "local",
        "judged_cases": 150,
    }
    return make_manifest(**{**data, **changes})


def base_manifest(**changes: Any) -> RunManifest:
    """Return the baseline manifest (``main@a1b2c3d``)."""
    data: dict[str, Any] = {
        "run_id": "20261101T220000-ba5e00",
        "git_sha": BASE_SHA,
        "git_ref": "main",
        "pr_number": None,
        "stack": "a40",
        "judge_mode": "local",
    }
    return manifest(**{**data, **changes})


def tier1_manifest(**changes: Any) -> RunManifest:
    """Return a tier-1 (``live``) candidate manifest with a GitHub Models judge."""
    data: dict[str, Any] = {
        "stack": "live",
        "splits": ["smoke_live"],
        "n_cases": 20,
        "duration_s": 843.0,
        "cost": CostSummary(
            usd=0, prompt_tokens=150_000, completion_tokens=50_000, gpu_seconds=0, llm_calls=3
        ),
        "judge_mode": "github",
        "judged_cases": 10,
    }
    return manifest(**{**data, **changes})


def tier1_base(**changes: Any) -> RunManifest:
    """Return the tier-1 baseline manifest."""
    return base_manifest(**{"stack": "live", "splits": ["smoke_live"], "n_cases": 20, **changes})


def info_row(
    metric: str,
    reason: str | None,
    base: float,
    cand: float,
    *,
    diff: float | None = None,
    mde: float | None = None,
    max_value: float | None = None,
) -> SliceDecision:
    """Return a non-gated PASS row (informational, reported or judged)."""
    ci = None if diff is None else (diff, diff - 0.1, diff + 0.1)
    return decision(
        metric,
        status=PASS,
        gated=False,
        base=base,
        cand=cand,
        ci=ci,
        mde=mde,
        max_drop=None,
        max_value=max_value,
        reason=reason,
    )


def notable_row(dimension: str, value: str, diff: float, *, notable: bool = True) -> SliceDecision:
    """Return a ``notable_slices`` entry (informational slice, no reason)."""
    return decision(
        dimension=dimension,
        value=value,
        status=PASS,
        gated=False,
        notable=notable,
        ci=(diff, diff - 0.1, diff + 0.1),
        mde=None,
        max_drop=None,
    )


def absolute_row(metric: str, cand: float, status: GateStatus = PASS) -> SliceDecision:
    """Return a gated absolute-check row (max 0.02)."""
    return decision(
        metric, status=status, base=0.0, cand=cand, ci=None, mde=None, max_drop=None, max_value=0.02
    )


def tier1_rows() -> dict[str, tuple[SliceDecision, ...]]:
    """Return the rows of a tier-1 PASS report: checks, reported pairs, informational, judged."""
    rep = "tier1_deterministic_only"
    reported = (
        info_row("language_match", rep, 1.0, 0.95, diff=-0.05, mde=0.21),
        info_row("citation_f1", rep, 0.9, 0.9, diff=0.0, mde=0.24),
        info_row("false_refusal", rep, 0.0, 0.0, diff=0.0),
        info_row("injection_success", "tier1_injection_reported", 0.0, 0.0, max_value=0.02),
    )
    info = info_row("refusal_correct", "refusal_outside_nightly_full", 1.0, 1.0, diff=0.0)
    judged = (
        info_row("faithfulness", "tier1_judged", 0.88, 0.85, diff=-0.03),
        info_row("answer_correctness", "tier1_judged", 0.91, 0.90, diff=-0.01),
    )
    checks = (absolute_row("error_rate", 0.0),)
    return {"reported": reported, "info": (info,), "judged": judged, "checks": checks}


def tier1_report(**changes: Any) -> GateReport:
    """Return the tier-1 PASS report (no hard fails)."""
    rows = tier1_rows()
    data: dict[str, Any] = {
        "status": PASS,
        "hard_fails": (),
        "decisions": (),
        "absolute_checks": rows["checks"],
        "notable_slices": (*rows["reported"], *rows["info"], *rows["judged"]),
        "top_failing_cases": ("law-0042",),
    }
    return gate_report(**{**data, **changes})


def no_baseline_report(**changes: Any) -> GateReport:
    """Return a no-baseline report (``baseline_run_id is None``, nothing compared)."""
    data: dict[str, Any] = {
        "status": INSUFFICIENT,
        "baseline_run_id": None,
        "no_baseline": True,
        "hard_fails": (),
        "decisions": (),
        "top_failing_cases": (),
    }
    return gate_report(**{**data, **changes})
