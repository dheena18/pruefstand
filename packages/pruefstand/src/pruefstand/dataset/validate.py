"""``validate_dataset``: one list of problems for a dataset directory (interfaces §14, T4.1 S3).

Always checked: schema (``file:line``), duplicate ids, ``base_id`` of a missing case, licence
configs, clusters spread over splits or mixing share-alike licences, ``corpus_version``, manifest
counts, ``block`` / ``judged_subset`` consistency. Quotas (``validate_quota``) are problems on
real builds and logged warnings on ``datasets/fixtures/*`` (D9-33); warnings are never returned.
"""

from collections import defaultdict
from pathlib import Path

from pruefstand.core.enums import Split
from pruefstand.core.models.dataset import DatasetManifest
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import LoadedDataset, read_dataset
from pruefstand.dataset.licenses import LICENSE_CONFIGS, SHARE_ALIKE_CONFIGS
from pruefstand.dataset.splits import assignment_summary
from pruefstand.dataset.validate_quota import check_quotas
from pruefstand.dataset.validate_report import Findings, is_fixture

_DERIVED_SPLITS = frozenset({Split.SMOKE_LIVE, Split.HUMAN_LABELS})
"""Splits that reuse cases of other splits; excluded from the cluster-disjointness check."""
_ORDER = {s: i for i, s in enumerate(Split)}


def _per_split(loaded: LoadedDataset, manifest: DatasetManifest, out: Findings) -> list[TestCase]:
    seen: dict[str, Split] = {}
    all_cases: list[TestCase] = []
    for split, cases in loaded.cases.items():
        expected = manifest.splits[split]
        if expected != len(cases):
            out.problem(f"{split.value}: manifest says {expected} cases, the file has {len(cases)}")
        for c in cases:
            if c.split is not split:
                out.problem(f"case {c.id!r}: split {c.split.value!r} in {split.value}.jsonl")
            if c.corpus_version != manifest.corpus_version:
                out.problem(f"case {c.id!r}: corpus_version differs from the manifest")
            if c.id in seen:
                out.problem(f"duplicate case id {c.id!r} ({seen[c.id].value}, {split.value})")
            seen[c.id] = split
        all_cases += cases
    return all_cases


def _licenses(cases: list[TestCase], manifest: DatasetManifest, out: Findings) -> None:
    bad: dict[str, list[str]] = defaultdict(list)
    for c in cases:
        if c.license_config not in LICENSE_CONFIGS:
            bad[c.license_config].append(c.id)
        elif c.license_config not in manifest.license_configs:
            out.problem(f"case {c.id!r}: license_config {c.license_config!r} not in the manifest")
    allowed = ", ".join(sorted(LICENSE_CONFIGS))
    for config, ids in sorted(bad.items()):
        out.problem(f"license_config {config!r} is not one of {allowed} (e.g. case {ids[0]!r})")
    by_cluster: dict[str, set[str]] = defaultdict(set)
    for c in cases:
        by_cluster[c.cluster_id].add(c.license_config)
    for cluster, configs in sorted(by_cluster.items()):
        mixed = sorted(configs & SHARE_ALIKE_CONFIGS)
        if len(mixed) > 1:
            out.problem(f"cluster {cluster} mixes licence configs {', '.join(mixed)}")


def _clusters(loaded: LoadedDataset, out: Findings) -> None:
    spread: dict[str, set[Split]] = defaultdict(set)
    for split, cases in loaded.cases.items():
        if split not in _DERIVED_SPLITS:
            for c in cases:
                spread[c.cluster_id].add(split)
    for cluster, splits in sorted(spread.items()):
        if len(splits) > 1:
            names = ",".join(s.value for s in sorted(splits, key=_ORDER.__getitem__))
            out.problem(f"cluster {cluster} spans {names}")


def _bases(cases: list[TestCase], out: Findings) -> None:
    ids = {c.id for c in cases}
    for c in cases:
        if c.base_id not in ids:
            out.problem(f"case {c.id!r}: base_id {c.base_id!r} is not a case of the dataset")
    by_id = {c.id: c for c in cases}
    for c in cases:
        base = by_id.get(c.base_id)
        if c.perturbation and base is not None and base.cluster_id != c.cluster_id:
            out.problem(f"case {c.id!r}: cluster {c.cluster_id!r} differs from its base's")
    based = {c.base_id for c in cases if c.perturbation}
    for c in cases:
        if c.split is Split.ROBUST_PR and c.perturbation is None and c.id not in based:
            out.problem(f"robust_pr case {c.id!r} has no perturbation and is not a base")


def _blocks(
    loaded: LoadedDataset, manifest: DatasetManifest, cases: list[TestCase], out: Findings
) -> None:
    blocks_of: dict[str, set[int]] = defaultdict(set)
    for c in loaded.cases.get(Split.FULL, []):
        refusal = c.category.value == "unanswerable"
        if refusal and c.block is not None:
            out.problem(f"full case {c.id!r} is in the refusal stratum and must not have a block")
        if not refusal and c.block is None:
            out.problem(f"full case {c.id!r} needs a block (0, 1 or 2)")
        if c.block is not None:
            blocks_of[c.cluster_id].add(c.block)
    for cluster, blocks in sorted(blocks_of.items()):
        if len(blocks) > 1:
            out.problem(f"cluster {cluster} spans blocks {','.join(map(str, sorted(blocks)))}")
    in_scope = [c for c in cases if c.split not in _DERIVED_SPLITS]
    rows_blocks, subset, _ = assignment_summary(in_scope, manifest.assignment_seed)
    if rows_blocks != manifest.blocks:
        out.problem(f"manifest blocks {manifest.blocks} differ from the rows {rows_blocks}")
    if subset != manifest.judged_subset:
        out.problem(
            f"manifest judged_subset {manifest.judged_subset} differs from the rows {subset}"
        )


def validate_dataset(dir: Path) -> list[str]:  # noqa: A002  (name fixed by interfaces §14)
    """Check a dataset directory and return its problems (empty list = valid).

    Warnings (quota findings of ``datasets/fixtures/*``) are logged and not returned.

    Args:
        dir: ``datasets/<name>/<version>/``.

    Returns:
        Human-readable problems, schema errors as ``<file>.jsonl:<line>: <reason>``.
    """
    loaded = read_dataset(dir)
    out = Findings(fixture=is_fixture(dir))
    out.problems += loaded.problems
    manifest = loaded.manifest
    if manifest is None:
        return out.problems
    cases = _per_split(loaded, manifest, out)
    _licenses(cases, manifest, out)
    _clusters(loaded, out)
    _bases(cases, out)
    _blocks(loaded, manifest, cases, out)
    check_quotas(loaded, manifest, out)
    return out.problems
