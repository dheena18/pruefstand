"""Inputs of ``core.fingerprint.eval_fingerprint`` that depend on the run (T1.10 S4b, X3.3).

Only the judges of **gated** judged metrics enter the fingerprint: tier 1 passes none. The
fingerprint itself is always computed by ``pruefstand.core.fingerprint``.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import resources

import yaml

from pruefstand.core.config import PruefstandConfig
from pruefstand.core.config.gate import JUDGED_METRICS
from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError
from pruefstand.core.fingerprint import eval_fingerprint
from pruefstand.core.logging import get_logger
from pruefstand.judges.output import SPECS
from pruefstand.llm.providers import catalogue_entry
from pruefstand.pipeline.judge_mode import Stack
from pruefstand.pipeline.select import Stratum, Tier

_log = get_logger(__name__)
_CALIBRATION = "calibration_status.yaml"
_MAX_CALIBRATION_BYTES = 100_000


@dataclass(frozen=True)
class JudgeFacts:
    """The judge part of ``RunManifest`` and of the fingerprint.

    Attributes:
        models: Gated judged metric to judge model id.
        prompt_versions: Gated judged metric to its judge prompt (``faithfulness_de_v2``).
        serving: Gated judged metric to ``"<engine> <version> <quantization> <digest[:12]>"``.
        epoch: Calibration epoch (0 while ``judges/data/calibration_status.yaml`` is missing).
    """

    models: dict[str, str]
    prompt_versions: dict[str, str]
    serving: dict[str, str]
    epoch: int


def calibration_epoch() -> int:
    """Read the calibration epoch from ``judges/data/calibration_status.yaml`` (T5.4).

    Returns:
        The ``epoch`` value, or 0 while the file does not exist.

    Raises:
        ConfigError: The file exists but has no non-negative integer ``epoch``.
    """
    path = resources.files("pruefstand.judges") / "data" / _CALIBRATION
    if not path.is_file():
        return 0
    raw = path.read_bytes()[: _MAX_CALIBRATION_BYTES + 1]
    try:
        data = yaml.safe_load(raw) if len(raw) <= _MAX_CALIBRATION_BYTES else None
    except yaml.YAMLError:
        data = None
    epoch = data.get("epoch") if isinstance(data, dict) else None
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
        msg = f"{_CALIBRATION}: needs a non-negative integer 'epoch'"
        raise ConfigError(msg)
    return epoch


def judge_serving(model_id: str) -> str | None:
    """Describe how a judge is served: ``"<engine> <tag> <quantization> <digest[:12]>"``.

    An Ollama judge reads its catalogue entry (the digest pins the exact weights; the Ollama
    server version is not known offline). Any other judge, or one the catalogue does not list,
    gets None.

    Examples:
        >>> judge_serving("github/openai/gpt-4.1-mini") is None
        True
    """
    if not model_id.startswith("ollama/"):
        return None
    try:
        entry = catalogue_entry(model_id)
    except ConfigError:
        _log.warning("judge_serving_unknown", model=model_id)
        return None
    digest = (entry.digest or "unpinned")[:12]
    return f"ollama {entry.tag} {entry.quantization or 'unknown'} {digest}"


def judge_facts(
    cfg: PruefstandConfig,
    *,
    stack: Stack,
    tier: Tier,
    serving: Mapping[str, str] | None = None,
    epoch: int | None = None,
) -> JudgeFacts:
    """Collect the judges of the gated judged metrics.

    Tier 1 (``stack="live"``) gates no judged metric, so it passes ``{}`` for the three
    mappings (the epoch still counts).

    Args:
        cfg: The run configuration.
        stack: ``live`` or ``a40``.
        tier: ``pr``, ``nightly`` or ``bench``; the nightly judge is used for ``nightly``.
        serving: Serving info of the judges by metric; default ``judge_serving`` of the catalogue.
        epoch: Calibration epoch; default is read from the calibration file.

    Returns:
        The judge facts.
    """
    value = calibration_epoch() if epoch is None else epoch
    if stack == "live":
        return JudgeFacts({}, {}, {}, value)
    default = cfg.judge.nightly if tier == "nightly" else cfg.judge.pr
    gated = sorted(set(cfg.gate.metrics) & JUDGED_METRICS)
    models = {m: cfg.judge.per_metric.get(m, default).id for m in gated}
    known = dict(serving) if serving is not None else {}
    if serving is None:
        found = {m: judge_serving(models[m]) for m in gated}
        known = {m: text for m, text in found.items() if text is not None}
    versions = {m: f"{SPECS[m].prompt_id}_{SPECS[m].version}" for m in gated}
    return JudgeFacts(models, versions, {m: known[m] for m in gated if m in known}, value)


def build_eval_fingerprint(  # noqa: PLR0913  (a thin wrapper over the fixed core signature)
    judges: JudgeFacts,
    *,
    name: str,
    version: str,
    corpus_version: str,
    splits: Sequence[Split],
    metric_versions: Mapping[str, str],
    block: int | None = None,
    judged_subset: bool = False,
    stratum: Stratum = "all",
) -> str:
    """Compute ``eval_fingerprint`` for a run (a call of ``core.fingerprint.eval_fingerprint``).

    Args:
        judges: From ``judge_facts``.
        name: Dataset name.
        version: Dataset version.
        corpus_version: Corpus version of the dataset.
        splits: Splits run.
        metric_versions: Metric name to version.
        block: Nightly block or None.
        judged_subset: Whether the judged subset limits the run.
        stratum: Case selector inside ``full``.

    Returns:
        16 hex characters.
    """
    return eval_fingerprint(
        dataset_name=name,
        dataset_version=version,
        splits=splits,
        judge_models=judges.models,
        judge_prompt_versions=judges.prompt_versions,
        judge_serving=judges.serving,
        judge_epoch=judges.epoch,
        metric_versions=metric_versions,
        corpus_version=corpus_version,
        block=block,
        judged_subset=judged_subset,
        stratum=stratum,
    )
