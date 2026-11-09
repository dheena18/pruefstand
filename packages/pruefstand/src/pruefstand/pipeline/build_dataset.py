"""``build_dataset``: generate -> filter -> perturb -> attacks -> splits -> validate (T4.7a).

Each stage writes ``<work_dir>/<build>/stage_<n>_<name>.jsonl`` (git-ignored) and a meta file with
the hash of its inputs. ``resume=True`` skips stages whose output exists for the current inputs;
``stage=<name>`` runs one stage. The last stage writes ``<out_dir>/<name>/<dataset_version>/`` and
runs ``validate_dataset`` on it. The model review (``dataset.model_review``) is a separate step
(``make review-model``) because it needs the finished splits.
"""

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pruefstand.core.config import DatasetBuildConfig
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.corpus import CorpusManifest
from pruefstand.core.models.dataset import DatasetManifest
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import build_manifest
from pruefstand.dataset.splits import assign_splits_report
from pruefstand.pipeline.build_attacks import attacks_stage
from pruefstand.pipeline.build_clients import BuildClients, default_clients
from pruefstand.pipeline.build_context import BuildContext, StageResult
from pruefstand.pipeline.build_filter import filter_stage
from pruefstand.pipeline.build_generate import generate_stage, specs_of
from pruefstand.pipeline.build_perturb import perturb_stage
from pruefstand.pipeline.build_state import STAGES, Workdir, file_digest, input_hash
from pruefstand.pipeline.review_files import replace_dataset

_log = get_logger(__name__)
REPORT = "build_report.json"
_Run = Callable[[BuildContext], Awaitable[StageResult]]


@dataclass(frozen=True)
class BuildResult:
    """What ``build_dataset`` returns: the manifest, the written directory and the report."""

    manifest: DatasetManifest | None
    directory: Path
    report: dict[str, object]


def _read_manifest(corpus_dir: Path) -> CorpusManifest:
    path = corpus_dir / "manifest.json"
    try:
        return CorpusManifest.model_validate_json(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        msg = f"{path}: not a readable corpus manifest ({type(exc).__name__})"
        raise ConfigError(msg) from exc


async def _splits_stage(ctx: BuildContext) -> StageResult:
    cases = [*ctx.work.read("perturb", TestCase), *ctx.work.read("attacks", TestCase)]
    report = assign_splits_report(cases, ctx.cfg.split_plan, np.random.default_rng(ctx.cfg.seed))
    counters = {"input": len(cases), "kept": len(report.cases), "dropped": len(report.dropped)}
    counters.update({f"dropped_{k}": v for k, v in sorted(report.reasons.items())})
    counters.update({f"perturbed_{k.value}": v for k, v in sorted(report.n_perturbed.items())})
    return list(report.cases), counters


async def _validate_stage(ctx: BuildContext) -> StageResult:
    cases = ctx.work.read("splits", TestCase)
    versions = _prompt_versions(ctx)
    manifest = build_manifest(
        ctx.cfg.name, ctx.cfg.dataset_version, ctx.manifest.corpus_version, cases,
        seed=ctx.cfg.seed, prompt_versions=versions,
    )  # fmt: skip
    directory = ctx.cfg.out_dir / ctx.cfg.name / ctx.cfg.dataset_version
    replace_dataset(directory, cases, manifest)
    return [], {"cases": len(cases), **{f"split_{k.value}": v for k, v in manifest.splits.items()}}


def _prompt_versions(ctx: BuildContext) -> dict[str, str]:
    versions = dict(ctx.cfg.prompt_versions)
    for _, spec, _ in specs_of(ctx):
        versions.setdefault(spec.prompt_id, spec.version)
    for key, value in ctx.manifest.sources.items():
        if key.startswith("attacks"):
            versions.setdefault(key, value)
    return versions


_RUNNERS: dict[str, _Run] = {
    "generate": generate_stage,
    "filter": filter_stage,
    "perturb": perturb_stage,
    "attacks": attacks_stage,
    "splits": _splits_stage,
    "validate": _validate_stage,
}
_INPUTS: dict[str, tuple[str, ...]] = {
    "generate": (),
    "filter": ("generate",),
    "perturb": ("filter",),
    "attacks": (),
    "splits": ("perturb", "attacks"),
    "validate": ("splits",),
}


def _settings(ctx: BuildContext, name: str) -> object:
    cfg = ctx.cfg
    parts: dict[str, object] = {
        "generate": [cfg.generation, cfg.models, cfg.seed, ctx.only],
        "filter": [cfg.filters, cfg.embed, cfg.models.support if cfg.models else None],
        "perturb": [cfg.perturb, cfg.models, ctx.manifest.corpus_version],
        "attacks": [cfg.seed, cfg.corpus_config, ctx.manifest.corpus_version],
        "splits": [cfg.split_plan, cfg.seed],
        "validate": [cfg.name, cfg.dataset_version, cfg.prompt_versions, cfg.out_dir],
    }
    return parts[name]


def _digest_of(ctx: BuildContext, stage: str) -> str:
    meta = ctx.work.meta(stage)
    return meta.sha256 if meta else ""


def _wanted(ctx: BuildContext, name: str) -> str:
    digests = [_digest_of(ctx, d) for d in _INPUTS[name]]
    if name in {"generate", "attacks"}:
        digests.append(file_digest(ctx.cfg.corpus_dir / "manifest.json"))
    if name == "generate" and ctx.cfg.generation.candidates_from:
        digests.append(file_digest(ctx.cfg.generation.candidates_from))
    return input_hash(name, _settings(ctx, name), *digests)


async def run_stage(ctx: BuildContext, name: str, *, resume: bool) -> dict[str, int]:
    """Run one stage (or skip it when fresh and ``resume``); return its counters."""
    wanted = _wanted(ctx, name)
    if resume and ctx.work.is_fresh(name, wanted):
        _log.info("stage_skipped", stage=name)
        meta = ctx.work.meta(name)
        return meta.counters if meta else {}
    rows, counters = await _RUNNERS[name](ctx)
    ctx.work.write(name, wanted, rows, counters)
    return counters


async def run_build(
    cfg: DatasetBuildConfig,
    *,
    stage: str | None = None,
    only: str | None = None,
    resume: bool = False,
    clients: BuildClients | None = None,
    root: Path | None = None,
) -> BuildResult:
    """Run the stages and return the manifest (None below the last stage), directory and report.

    Takes the arguments of ``build_dataset``; the report holds the counters per stage and
    ``dropped_mixed_license``.
    """
    if stage is not None and stage not in STAGES:
        msg = f"unknown stage {stage!r}; stages: {', '.join(STAGES)}"
        raise ConfigError(msg)
    base = root or Path.cwd()
    manifest = _read_manifest(cfg.corpus_dir)
    work = Workdir(cfg.work_dir / f"{cfg.name}-{cfg.dataset_version}")
    ctx = BuildContext(cfg, work, clients or default_clients(base), manifest, base, only)
    names: Sequence[str] = [stage] if stage else STAGES
    counters = {name: await run_stage(ctx, name, resume=resume) for name in names}
    directory = cfg.out_dir / cfg.name / cfg.dataset_version
    written = directory / "dataset_manifest.json"
    final = (
        DatasetManifest.model_validate_json(written.read_text("utf-8"))
        if written.is_file()
        else None
    )
    perturb = work.meta("perturb")
    report: dict[str, object] = {
        "corpus_version": manifest.corpus_version,
        "stages": counters,
        "dropped_mixed_license": perturb.counters.get("dropped_mixed_license", 0) if perturb else 0,
    }
    work.root.mkdir(parents=True, exist_ok=True)
    (work.root / REPORT).write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", "utf-8")
    return BuildResult(final, directory, report)


async def build_dataset(
    cfg: DatasetBuildConfig,
    *,
    stage: str | None = None,
    only: str | None = None,
    resume: bool = False,
    clients: BuildClients | None = None,
    root: Path | None = None,
) -> DatasetManifest:
    """Build ``<out_dir>/<name>/<dataset_version>/`` from the corpus (interfaces §14).

    Args:
        cfg: The build configuration (``dataset.yaml``).
        stage: Run only this stage (it reads the earlier outputs).
        only: Restrict ``generate`` to one prompt id or version (regeneration of one prompt).
        resume: Skip stages whose output exists for the current inputs.
        clients: Model and embedding clients (tests inject their own).
        root: Repository root for the canary registry and cache (default: the working directory).

    Returns:
        The manifest of the written dataset.

    Raises:
        ConfigError: Unknown stage or an invalid setting.
        DatasetError: A stage failed, the written dataset does not validate, or the last stage did
            not run so there is no manifest yet.
    """
    result = await run_build(cfg, stage=stage, only=only, resume=resume, clients=clients, root=root)
    if result.manifest is None:
        msg = "no dataset manifest yet; run the validate stage"
        raise DatasetError(msg)
    return result.manifest
