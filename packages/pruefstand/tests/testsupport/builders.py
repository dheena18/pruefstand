"""Builders and fixtures F0/F1 for the gate tests (T1.7; reused by T1.9, T1.10, T1.11).

``make_run`` takes plain Python values: a float is an ``ok`` value, ``None`` is status ``error``
and ``NA`` (NaN) is status ``not_applicable``. The runs are real pydantic models, never fakes of a
model or a target: they carry numbers, as the statistical gate only ever sees numbers.
"""

import functools
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from pruefstand.core.enums import Category, Difficulty, Lang, Split
from pruefstand.core.models.metric import MetricStatus, MetricValue
from pruefstand.core.models.run import CostSummary, RunManifest, RunResults, ScoredCase
from pruefstand.core.models.target import CaseRecord, RetrievedChunk, TargetRequest, TargetResponse
from pruefstand.core.models.testcase import TestCase

NA = math.nan
"""Marker for ``not_applicable`` in ``make_run`` value lists."""

TENANTS = ("kanzlei_mueller", "versicherung_nord", "stadtwerke_sued")
F0_BASELINE = {
    "context_recall": 0.8,
    "faithfulness": 0.9,
    "citation_recall": 0.7,
    "language_match": 1.0,
    "error_rate": 0.0,
    "injection_success": 0.0,
    "canary_leak": 0.0,
    "tenant_leak": 0.0,
    "system_prompt_leak": 0.0,
}

Details = Mapping[str, Mapping[int, Mapping[str, str | float | int | bool]]]


def make_case(
    i: int,
    *,
    cluster: int,
    tenant: str = "kanzlei_mueller",
    lang: str = "de",
    category: str = "factual",
    perturbation: str | None = None,
    tags: tuple[str, ...] = (),
    base: int | None = None,
) -> TestCase:
    """Return a ``TestCase`` with ``id=c<i:04d>`` in the bootstrap cluster ``k<cluster:03d>``.

    Args:
        i: Case number.
        cluster: Cluster number.
        tenant: Tenant id.
        lang: ``de`` or ``en``.
        category: A ``Category`` value that needs no extra fields (``factual``, ``multi_hop``, ...).
        perturbation: ``None`` for a base case, else the perturbation name.
        tags: Free tags.
        base: Number of the base case of a perturbed case (default: a synthetic ``b<i>``).

    Returns:
        The case; ``base_id == id`` unless ``perturbation`` is set.
    """
    case_id = f"c{i:04d}"
    base_id = case_id
    if perturbation is not None:
        base_id = f"c{base:04d}" if base is not None else f"b{i:04d}"
    return TestCase(
        id=case_id,  # type: ignore[arg-type]  # NewType over str
        base_id=base_id,  # type: ignore[arg-type]  # NewType over str
        cluster_id=f"k{cluster:03d}",
        tenant=tenant,  # type: ignore[arg-type]  # NewType over str
        lang=Lang(lang),
        question=f"Frage {i}?",
        reference_answer="Antwort.",
        category=Category(category),
        difficulty=Difficulty.EASY,
        split=Split.CORE,
        perturbation=perturbation,
        source="test",
        license_config="test",
        corpus_version="cv-test",
        tags=tags,
        injection_marker="IGNORE-PREVIOUS-INSTRUCTIONS" if category == "injection" else None,
    )


def make_record(
    case: TestCase, *, chunks: bool | None = False, answered: bool = True
) -> CaseRecord:
    """Return the recorded exchange of ``case``.

    Args:
        case: The case.
        chunks: ``True``: the response carries (empty) ``chunks``; else it omits them.
        answered: ``False``: the request failed (no response).

    Returns:
        A ``CaseRecord``.
    """
    request = TargetRequest(tenant_id=case.tenant, question=case.question, request_id=case.id)
    response = None
    if answered:
        listed: tuple[RetrievedChunk, ...] | None = () if chunks else None
        response = TargetResponse(answer="Antwort", chunks=listed)
    return CaseRecord(
        case_id=case.id,
        request=request,
        response=response,
        error=None if answered else "timeout",
        latency_ms=1.0,
        cached=False,
        attempt=1,
    )


@functools.lru_cache(maxsize=8192)
def _plain_value(metric: str, number: float | None, status: MetricStatus) -> MetricValue:
    # MetricValue is frozen, so equal values can be shared; this and model_construct (the range is
    # checked in `_metric_value`) make 4 000 simulated runs of 300 cases fit the nightly budget
    return MetricValue.model_construct(
        metric=metric, metric_version="1", value=number, status=status, details={}
    )


def _metric_value(
    metric: str, value: float | None, details: Mapping[str, str | float | int | bool]
) -> MetricValue:
    if value is None:
        status, number = MetricStatus.ERROR, None
    elif math.isnan(value):
        status, number = MetricStatus.NOT_APPLICABLE, None
    else:
        status, number = MetricStatus.OK, value
        if not 0.0 <= number <= 1.0:
            msg = f"{metric}: value {number} is outside [0, 1]"
            raise ValueError(msg)
    if details:
        return MetricValue(
            metric=metric, metric_version="1", value=number, status=status, details=dict(details)
        )
    return _plain_value(metric, number, status)


def _manifest(
    run_id: str,
    n_cases: int,
    *,
    eval_fingerprint: str,
    complete: bool,
    counts: Mapping[str, int] | None,
    stack: str,
) -> RunManifest:
    return RunManifest(
        schema_version="1",
        run_id=run_id,  # type: ignore[arg-type]  # NewType over str
        created_at=datetime(2026, 11, 2, 22, 0, tzinfo=UTC),
        pruefstand_version="0.0.1",
        git_sha=None,
        git_ref=None,
        pr_number=None,
        target=None,
        target_fingerprint="t" * 16,
        eval_fingerprint=eval_fingerprint,
        dataset_name="pruefstand-de",
        dataset_version="v1",
        splits=(Split.CORE,),
        n_cases=n_cases,
        config_hash="c" * 16,
        judge_models={},
        judge_prompt_versions={},
        metric_versions={},
        seed=0,
        cost=CostSummary(usd=0, prompt_tokens=0, completion_tokens=0, gpu_seconds=0, llm_calls=0),
        duration_s=1.0,
        counts=dict(counts or {}),
        complete=complete,
        stop_reason="completed" if complete else "aborted",
        stack=stack,  # type: ignore[arg-type]  # Literal checked by pydantic
        workload="pr",
        judge_mode="local" if stack == "a40" else "skipped",
    )


def make_run(  # noqa: PLR0913  (builder fixed by the T1.7 prompt; extras are keyword-only)
    run_id: str,
    cases: Sequence[TestCase],
    values: Mapping[str, Sequence[float | None]],
    *,
    eval_fingerprint: str = "ef-test",
    complete: bool = True,
    counts: Mapping[str, int] | None = None,
    records: Sequence[CaseRecord] = (),
    details: Details | None = None,
    stack: str = "a40",
) -> RunResults:
    """Return a ``RunResults`` from per-metric value lists aligned with ``cases``.

    Args:
        run_id: Run id.
        cases: The cases, in run order.
        values: metric -> one entry per case: a float (``ok``), ``None`` (``error``) or ``NA``
            (``not_applicable``).
        eval_fingerprint: Evaluation fingerprint of the manifest.
        complete: ``False`` gives ``stop_reason="aborted"``.
        counts: ``RunManifest.counts``.
        records: Recorded target exchanges (default none).
        details: metric -> case index -> ``MetricValue.details``.
        stack: ``live`` or ``a40``.

    Returns:
        The run.

    Raises:
        ValueError: A value list does not have one entry per case.
    """
    for metric, column in values.items():
        if len(column) != len(cases):
            msg = f"{metric}: {len(column)} values for {len(cases)} cases"
            raise ValueError(msg)
    extra = details or {}
    scored = tuple(
        ScoredCase.model_construct(  # arguments are built right here; saves simulation time
            case=case,
            values=tuple(
                _metric_value(metric, column[i], extra.get(metric, {}).get(i, {}))
                for metric, column in values.items()
            ),
        )
        for i, case in enumerate(cases)
    )
    manifest = _manifest(
        run_id,
        len(cases),
        eval_fingerprint=eval_fingerprint,
        complete=complete,
        counts=counts,
        stack=stack,
    )
    return RunResults(manifest=manifest, records=tuple(records), values=scored)


def fixture_f0() -> tuple[list[TestCase], dict[str, list[float | None]]]:
    """F0: 120 cases = 60 clusters x 2; tenants in thirds; ``de`` for clusters 0-49, ``en`` 50-59.

    Returns:
        ``(cases, base_values)``; the baseline values are constant per metric (``F0_BASELINE``).
    """
    cases = [
        make_case(
            i,
            cluster=i // 2,
            tenant=TENANTS[i // 2 // 20],
            lang="de" if i // 2 < 50 else "en",
        )
        for i in range(120)
    ]
    return cases, {m: [v] * 120 for m, v in F0_BASELINE.items()}


def fixture_f1() -> tuple[list[TestCase], dict[str, list[float | None]]]:
    """F1: 40 clusters x (base, ``compound_split``, ``typos``) = 120 cases, one tenant, ``de``.

    Returns:
        ``(cases, base_values)`` with the F0 baseline values.
    """
    cases: list[TestCase] = []
    for cluster in range(40):
        first = 3 * cluster
        cases.append(make_case(first, cluster=cluster))
        for offset, name in ((1, "compound_split"), (2, "typos")):
            cases.append(make_case(first + offset, cluster=cluster, perturbation=name, base=first))
    return cases, {m: [v] * 120 for m, v in F0_BASELINE.items()}
