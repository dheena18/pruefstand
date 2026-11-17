"""No-op and churn variants of ``rag.gpu.yaml`` and the run plan of one noise arm (T6.3 S1).

Every variant is built deterministically from the committed ``rag.gpu.yaml`` (X3.5, AI9-09):

* no-op kinds (behaviour unchanged, answers regenerated): ``reindex`` (fresh collection from the
  same corpus), ``reorder`` (mapping keys permuted with a seeded generator, same values; list
  order is meaning, so lists stay as they are) and ``rebuild`` (``docker build --no-cache`` of the
  same commit, new digest);
* churn kinds (behaviour-neutral, answers change): ``prompt_synonym`` (mutation N04,
  ``answer_de_v3.txt``), ``quant_swap`` (mutation N09, a second quantisation tag) and ``temp03``
  (``generation.temperature: 0.3``);
* ``repeats``: the unchanged config, ``--cache-mode production`` or ``off`` (the floor).

Each plan starts with a reference run of ``main`` (index 0) and adds ``repeats`` variant runs.
In ``noop`` and ``churn`` mode every run regenerates: its own ``generation.seed`` (``seed + i``),
which changes the rag-demo config hash and with it the target fingerprint, so the target cache
cannot hit; the index is rebuilt for every no-op run. The judge cache stays on.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast

import numpy as np
import yaml
from mutations.apply import merge_overrides
from mutations.schema import load_index, load_spec
from pydantic import BaseModel, ConfigDict, JsonValue

from pruefstand.core.errors import ConfigError

REPO = Path(__file__).resolve().parents[2]
GPU_CONFIG = REPO / "apps/rag-demo/configs/rag.gpu.yaml"
Mode = Literal["repeats", "noop", "churn"]
NoopKind = Literal["reindex", "reorder", "rebuild"]
ChurnKind = Literal["prompt_synonym", "quant_swap", "temp03"]
CacheMode = Literal["production", "off"]
CHURN_MUTATION: Mapping[str, str] = {"prompt_synonym": "N04", "quant_swap": "N09"}
TEMP03: Mapping[str, JsonValue] = {"generation": {"temperature": 0.3}}


class PlannedRun(BaseModel):
    """One run of a noise arm: the rag-demo config, how it is served and how it is cached."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int
    label: str
    config: dict[str, JsonValue]
    mutation: str | None = None  # a benchmarks/mutations entry applied in the candidate worktree
    rebuild_index: bool
    rebuild_image: bool
    target_cache: CacheMode
    judge_cache: CacheMode
    collection: str


def load_base(path: Path = GPU_CONFIG) -> dict[str, JsonValue]:
    """The committed ``rag.gpu.yaml`` as a mapping.

    Raises:
        ConfigError: the file is not a YAML mapping.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"{path}: not a YAML mapping"
        raise ConfigError(msg)
    return data


def reorder(config: Mapping[str, JsonValue], rng: np.random.Generator) -> dict[str, JsonValue]:
    """The same mapping with every level's keys in a random order (values and lists unchanged).

    Examples:
        >>> out = reorder({"a": 1, "b": {"x": 1, "y": 2}, "c": [1, 2]}, np.random.default_rng(0))
        >>> out == {"a": 1, "b": {"x": 1, "y": 2}, "c": [1, 2]}
        True
    """
    keys = list(config)
    order = rng.permutation(len(keys))
    out: dict[str, JsonValue] = {}
    for i in order:
        value = config[keys[int(i)]]
        out[keys[int(i)]] = reorder(value, rng) if isinstance(value, Mapping) else value
    return out


def churn_overrides(kind: ChurnKind) -> tuple[dict[str, JsonValue], str | None]:
    """``rag.gpu.yaml`` overrides and the mutation entry (if any) of a churn kind.

    Raises:
        ConfigError: the kind's mutation entry is pending (e.g. N09 until a second quantisation tag
            is in the catalogue and on the cluster disk).
    """
    if kind == "temp03":
        return dict(TEMP03), None
    entry = CHURN_MUTATION[kind]
    pending = load_index().pending
    if entry in pending:
        msg = f"churn kind {kind}: mutation {entry} is pending: {pending[entry].strip()}"
        raise ConfigError(msg)
    spec = load_spec(entry)
    if spec.rag_overrides is not None:
        return dict(spec.rag_overrides), entry
    return {}, entry  # a patch entry (N04): the overrides come with the patch


def with_seed(config: Mapping[str, JsonValue], seed: int) -> dict[str, JsonValue]:
    """``config`` with ``generation.seed`` set to ``seed``."""
    return merge_overrides(config, {"generation": {"seed": seed}})


def _variant(
    mode: Mode, kind: str | None, base: Mapping[str, JsonValue], rng: np.random.Generator
) -> tuple[dict[str, JsonValue], str | None]:
    if mode == "noop" and kind == "reorder":
        return reorder(base, rng), None
    if mode == "churn":
        overrides, mutation = churn_overrides(cast("ChurnKind", kind))  # kind checked by _check
        return merge_overrides(base, overrides), mutation
    return dict(base), None


def build_plan(
    mode: Mode,
    kind: str | None,
    *,
    repeats: int,
    cache_mode: CacheMode,
    seed: int,
    base: Mapping[str, JsonValue] | None = None,
) -> list[PlannedRun]:
    """The reference ``main`` run (index 0) and ``repeats`` runs of the arm (deterministic).

    Raises:
        ConfigError: a kind that does not belong to the mode, ``repeats < 1``, a cache mode other
            than ``production`` outside ``repeats`` mode, or a pending churn mutation.
    """
    _check(mode, kind, repeats, cache_mode)
    config = load_base() if base is None else dict(base)
    rng = np.random.default_rng(seed)
    variant, mutation = _variant(mode, kind, config, rng)
    regenerate = mode != "repeats"
    target_cache: CacheMode = "off" if regenerate else cache_mode
    runs: list[PlannedRun] = []
    for i in range(repeats + 1):
        body = config if i == 0 else variant
        runs.append(
            PlannedRun(
                index=i,
                label="main" if i == 0 else f"{mode}-{kind or cache_mode}-{i}",
                config=with_seed(body, seed + i) if regenerate else dict(body),
                mutation=None if i == 0 else mutation,
                rebuild_index=mode == "noop",
                rebuild_image=mode == "noop" and kind == "rebuild" and i > 0,
                target_cache=target_cache,
                judge_cache="off" if cache_mode == "off" else "production",
                collection=f"noise_{mode}_{kind or cache_mode}_{i}",
            )
        )
    return runs


KINDS: Mapping[str, tuple[str, ...]] = {
    "noop": ("reindex", "reorder", "rebuild"),
    "churn": ("prompt_synonym", "quant_swap", "temp03"),
}


def _check(mode: Mode, kind: str | None, repeats: int, cache_mode: CacheMode) -> None:
    allowed = KINDS.get(mode, ())
    problem = None
    if repeats < 1:
        problem = f"--repeats must be >= 1, got {repeats}"
    elif mode == "repeats" and kind is not None:
        problem = "--mode repeats takes no kind"
    elif mode != "repeats" and kind not in allowed:
        problem = f"--mode {mode} needs a kind in {list(allowed)}, got {kind!r}"
    elif mode != "repeats" and cache_mode != "production":
        problem = f"--mode {mode} always regenerates; --cache-mode applies to --mode repeats only"
    if problem is not None:
        raise ConfigError(problem)
