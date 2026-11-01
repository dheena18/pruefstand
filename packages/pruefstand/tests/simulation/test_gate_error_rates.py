"""Monte-Carlo validation of the gate maths (testing-strategy §3.4, SPEC §7.2).

Simulated numbers because the true delta must be known; this tests the statistics, not the product.
Grid size via ``PRUEFSTAND_SIM_GRID``: ``reduced`` (default: 500 sims, alpha + 4 SE) or ``full``
(nightly, 4 000 sims, bound alpha + 3 SE). If a bound fails, report the numbers; never tune.
"""

import csv
import math
import os
import tempfile
from pathlib import Path
from typing import Literal

import numpy as np
import pytest
from testsupport.sim_data import simulate_paired

from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import BootstrapResult
from pruefstand.gate.decision import decide
from pruefstand.gate.stats import paired_cluster_bootstrap, power_estimate

SEED = 20261027
DELTA = 0.03
ALPHA = 0.025
FULL = os.environ.get("PRUEFSTAND_SIM_GRID", "reduced") == "full"
N_SIMS = 4000 if FULL else 500
B = 400
_SE = math.sqrt(ALPHA * (1 - ALPHA) / N_SIMS)
TYPE1_BOUND = ALPHA + (3 if FULL else 4) * _SE  # 0.03241 (full) / 0.0529 (reduced)
POWER_FLOOR = 0.80 if FULL else 0.80 - 4 * math.sqrt(0.16 / N_SIMS)  # 0.728 (reduced)
FORMULA_TOL = 0.05 if FULL else 0.05 + 4 * math.sqrt(0.25 / N_SIMS)  # 0.139 (reduced)
OUT_DIR = Path("build/simulation")
COLUMNS = [
    "kind", "sigma_d", "discordance", "n_clusters", "cluster_size", "true_drop", "fail_rate",
    "warn_rate", "power_estimate", "raw_p_rate",
]  # fmt: skip
Kind = Literal["gaussian", "binary"]


def _rates(  # noqa: PLR0913  (cell description)
    *,
    kind: Kind,
    sigma_d: float,
    discordance: float,
    n_clusters: int,
    cluster_size: int,
    true_delta: float,
    n_sims: int,
    n_resamples: int,
    seed_parts: tuple[int, ...],
    cluster_sizes: list[int] | None = None,
) -> tuple[float, float, float]:
    rng = np.random.default_rng([SEED, *seed_parts])
    diffs, clusters = simulate_paired(
        n_clusters, cluster_size, true_delta, sigma_d=sigma_d, icc=0.3, kind=kind,
        discordance=discordance, rng=rng, cluster_sizes=cluster_sizes, n_sims=n_sims,
    )  # fmt: skip
    counts = {GateStatus.FAIL: 0, GateStatus.WARN: 0}
    raw = 0  # p < alpha alone, without the relevance (max_drop) condition
    for row in diffs:
        r: BootstrapResult = paired_cluster_bootstrap(
            row, clusters, n_resamples=n_resamples, confidence=0.95, rng=rng, alpha=ALPHA
        )
        s = decide(
            r, max_drop=DELTA, p_adjusted=r.p_value, alpha=ALPHA, warn_p=0.10, min_clusters=30,
            gated=True,
        )  # fmt: skip
        raw += r.p_value < ALPHA
        if s in counts:
            counts[s] += 1
    return counts[GateStatus.FAIL] / n_sims, counts[GateStatus.WARN] / n_sims, raw / n_sims


def _record(name: str, row: dict[str, object], out_dir: Path | None = None) -> None:
    """Write one row for this cell and rebuild the combined CSV (xdist runs cells in parallel)."""
    out = out_dir or OUT_DIR
    cells = out / "cells"
    cells.mkdir(parents=True, exist_ok=True)
    (cells / f"{name}.csv").write_text(",".join(str(row.get(c, "")) for c in COLUMNS) + "\n")
    lines = [p.read_text() for p in sorted(cells.glob("*.csv"))]
    with tempfile.NamedTemporaryFile("w", dir=out, delete=False, suffix=".tmp") as tmp:
        tmp.write(",".join(COLUMNS) + "\n" + "".join(lines))
    Path(tmp.name).replace(out / "power_curves.csv")


def _cell(  # noqa: PLR0913  (cell description)
    name: str,
    *,
    kind: Kind,
    sigma_d: float = 0.0,
    discordance: float = 0.0,
    n_clusters: int,
    cluster_size: int = 2,
    true_drop: float,
    seed_parts: tuple[int, ...],
    cluster_sizes: list[int] | None = None,
) -> tuple[float, float, float]:
    fail, warn, raw = _rates(
        kind=kind, sigma_d=sigma_d, discordance=discordance, n_clusters=n_clusters,
        cluster_size=cluster_size, true_delta=-true_drop, n_sims=N_SIMS, n_resamples=B,
        seed_parts=seed_parts, cluster_sizes=cluster_sizes,
    )  # fmt: skip
    pe = (
        power_estimate(sigma_d, n_clusters, DELTA, ALPHA, true_drop=true_drop)
        if kind == "gaussian" and cluster_size == 1 and cluster_sizes is None
        else ""
    )
    _record(
        name,
        {
            "kind": kind, "sigma_d": sigma_d, "discordance": discordance, "n_clusters": n_clusters,
            "cluster_size": cluster_size if cluster_sizes is None else "40x10+180x1",
            "true_drop": true_drop, "fail_rate": fail,
            "warn_rate": warn, "power_estimate": pe, "raw_p_rate": raw,
        },
    )  # fmt: skip
    return fail, warn, raw


def test_tiny_type1_runs_in_make_test() -> None:
    fail, _, _ = _rates(
        kind="gaussian", sigma_d=0.25, discordance=0.0, n_clusters=50, cluster_size=2,
        true_delta=0.0, n_sims=400, n_resamples=200, seed_parts=(0,),
    )  # fmt: skip
    assert fail <= ALPHA + 0.03


@pytest.mark.slow
@pytest.mark.parametrize("n_clusters", [30, 50, 300])
@pytest.mark.parametrize("sigma_d", [0.15, 0.25, 0.40])
def test_type1_gaussian(sigma_d: float, n_clusters: int) -> None:
    fail, _, raw = _cell(
        f"type1_gaussian_{sigma_d}_{n_clusters}", kind="gaussian", sigma_d=sigma_d,
        n_clusters=n_clusters, true_drop=0.0, seed_parts=(1, round(sigma_d * 100), n_clusters),
    )  # fmt: skip
    assert fail <= TYPE1_BOUND, f"type-I FAIL rate {fail:.4f} > {TYPE1_BOUND:.4f}"
    assert raw <= TYPE1_BOUND, f"raw p < alpha rate {raw:.4f} > {TYPE1_BOUND:.4f}"


@pytest.mark.slow
@pytest.mark.parametrize("n_clusters", [30, 50, 300])
@pytest.mark.parametrize("discordance", [0.02, 0.05, 0.10])
def test_type1_binary(discordance: float, n_clusters: int) -> None:
    fail, _, _ = _cell(
        f"type1_binary_{discordance}_{n_clusters}", kind="binary", discordance=discordance,
        n_clusters=n_clusters, true_drop=0.0, seed_parts=(2, round(discordance * 100), n_clusters),
    )  # fmt: skip
    assert fail <= TYPE1_BOUND, f"type-I FAIL rate {fail:.4f} > {TYPE1_BOUND:.4f}"


@pytest.mark.slow
def test_type1_heterogeneous_cluster_sizes() -> None:
    fail, _, raw = _cell(
        "type1_hetero", kind="gaussian", sigma_d=0.25, n_clusters=220, cluster_size=0,
        true_drop=0.0, seed_parts=(3,), cluster_sizes=[10] * 40 + [1] * 180,
    )  # fmt: skip
    assert fail <= TYPE1_BOUND, f"type-I FAIL rate {fail:.4f} > {TYPE1_BOUND:.4f}"
    assert raw <= TYPE1_BOUND, f"raw p < alpha rate {raw:.4f} > {TYPE1_BOUND:.4f}"


@pytest.mark.slow
def test_power_sigma025_n300() -> None:
    fail, _, _ = _cell(
        "power_gaussian_0.25_300", kind="gaussian", sigma_d=0.25, n_clusters=300,
        true_drop=2 * DELTA, seed_parts=(4,),
    )  # fmt: skip
    assert fail >= POWER_FLOOR, f"power {fail:.4f} < {POWER_FLOOR:.4f}"


@pytest.mark.slow
@pytest.mark.parametrize("n_clusters", [50, 300])
@pytest.mark.parametrize("sigma_d", [0.15, 0.25, 0.40])
def test_formula_matches_simulation(sigma_d: float, n_clusters: int) -> None:
    fail, _, _ = _cell(
        f"formula_gaussian_{sigma_d}_{n_clusters}", kind="gaussian", sigma_d=sigma_d,
        n_clusters=n_clusters, cluster_size=1, true_drop=2 * DELTA,
        seed_parts=(5, round(sigma_d * 100), n_clusters),
    )  # fmt: skip
    expected = power_estimate(sigma_d, n_clusters, DELTA, ALPHA)
    assert abs(fail - expected) <= FORMULA_TOL, f"observed {fail:.3f} vs formula {expected:.3f}"


@pytest.mark.slow
def test_cluster_bootstrap_beats_naive_with_high_icc() -> None:
    """With icc 0.8 the cluster bootstrap stays within the bound, the per-case one does not."""
    rng = np.random.default_rng([SEED, 6])
    diffs, clusters = simulate_paired(
        30, 10, 0.0, sigma_d=0.25, icc=0.8, kind="gaussian", discordance=0.0, rng=rng,
        n_sims=N_SIMS,
    )  # fmt: skip
    singles = np.array([f"c{i}" for i in range(diffs.shape[1])])
    fails = {"cluster": 0, "naive": 0}
    for row in diffs:
        for name, ids in (("cluster", clusters), ("naive", singles)):
            r = paired_cluster_bootstrap(
                row, ids, n_resamples=B, confidence=0.95, rng=rng, alpha=ALPHA
            )
            s = decide(
                r, max_drop=0.0, p_adjusted=r.p_value, alpha=ALPHA, warn_p=0.10, min_clusters=30,
                gated=True,
            )  # fmt: skip
            fails[name] += s is GateStatus.FAIL
    assert fails["cluster"] / N_SIMS <= TYPE1_BOUND
    assert fails["naive"] / N_SIMS > TYPE1_BOUND


def test_record_writes_combined_csv(tmp_path: Path) -> None:
    _record("x", {"kind": "gaussian", "fail_rate": 0.1}, tmp_path)
    rows = list(csv.reader((tmp_path / "power_curves.csv").open()))
    assert rows[0] == COLUMNS
    assert rows[1][0] == "gaussian"
