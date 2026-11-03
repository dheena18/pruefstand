"""T3.1a CPU tests: the rerank thread cap comes from the container's cgroup CPU quota (D650)."""

from pathlib import Path

import pytest
from rerank.rerank_app import cpu_limit


@pytest.fixture(autouse=True)
def _no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RERANK_THREADS", raising=False)


def test_cgroup_v2_quota_of_eight_cpus_caps_a_160_core_host(tmp_path: Path) -> None:
    (tmp_path / "cpu.max").write_text("800000 100000\n", encoding="utf-8")
    assert cpu_limit(tmp_path, cores=160) == 8


def test_a_fractional_v2_quota_rounds_up(tmp_path: Path) -> None:
    (tmp_path / "cpu.max").write_text("150000 100000\n", encoding="utf-8")
    assert cpu_limit(tmp_path, cores=160) == 2


def test_v2_max_means_no_quota_so_the_visible_cores_count(tmp_path: Path) -> None:
    (tmp_path / "cpu.max").write_text("max 100000\n", encoding="utf-8")
    assert cpu_limit(tmp_path, cores=6) == 6


def test_cgroup_v1_quota_and_period(tmp_path: Path) -> None:
    (tmp_path / "cpu").mkdir()
    (tmp_path / "cpu" / "cpu.cfs_quota_us").write_text("400000\n", encoding="utf-8")
    (tmp_path / "cpu" / "cpu.cfs_period_us").write_text("100000\n", encoding="utf-8")
    assert cpu_limit(tmp_path, cores=160) == 4


def test_cgroup_v1_without_a_quota_uses_the_visible_cores(tmp_path: Path) -> None:
    (tmp_path / "cpu").mkdir()
    (tmp_path / "cpu" / "cpu.cfs_quota_us").write_text("-1\n", encoding="utf-8")
    (tmp_path / "cpu" / "cpu.cfs_period_us").write_text("100000\n", encoding="utf-8")
    assert cpu_limit(tmp_path, cores=12) == 12


def test_the_quota_never_exceeds_the_visible_cores(tmp_path: Path) -> None:
    (tmp_path / "cpu.max").write_text("800000 100000\n", encoding="utf-8")
    assert cpu_limit(tmp_path, cores=4) == 4


@pytest.mark.parametrize("content", ["", "garbage", "100 0", "x y"])
def test_unreadable_or_invalid_cgroup_files_fall_back_to_the_visible_cores(
    tmp_path: Path, content: str
) -> None:
    (tmp_path / "cpu.max").write_text(content, encoding="utf-8")
    assert cpu_limit(tmp_path, cores=16) == 16


def test_no_cgroup_files_at_all_use_the_visible_cores(tmp_path: Path) -> None:
    assert cpu_limit(tmp_path / "missing", cores=3) == 3


def test_the_override_wins_and_a_bad_override_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "cpu.max").write_text("800000 100000\n", encoding="utf-8")
    monkeypatch.setenv("RERANK_THREADS", "2")
    assert cpu_limit(tmp_path, cores=160) == 2
    monkeypatch.setenv("RERANK_THREADS", "0")
    assert cpu_limit(tmp_path, cores=160) == 8
    monkeypatch.setenv("RERANK_THREADS", "abc")
    assert cpu_limit(tmp_path, cores=160) == 8


def test_the_real_host_returns_at_least_one_thread() -> None:
    assert cpu_limit() >= 1
