"""gate_job (X2.1, D226, D1095): maintenance skips the run; failed checks post an error."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from gate_orchestrator.gate_job import Attempt, run_gate_job
from gate_orchestrator.models import Job
from gate_orchestrator.status import MAINTENANCE
from orch_testkit import SpyPoster

SHA = "a" * 40


def _attempt(
    tmp: Path, poster: SpyPoster, calls: list[list[str]], *, tunnel_up: bool, label: str = ""
) -> Attempt:
    def run(argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        calls.append(list(argv))
        if list(argv[:2]) == ["systemctl", "is-active"]:
            return (0 if tunnel_up else 3), ""
        if list(argv[:3]) == ["docker", "image", "inspect"]:
            return 0, json.dumps({"org.opencontainers.image.revision": label})
        return 0, ""

    return Attempt(
        job=Job(kind="gate", sha=SHA, pr_number=7, tier="pr"),
        digest="sha256:" + "b" * 64,
        run=run,
        poster=poster,
        statuses=lambda sha: [],
        main_config=tmp / "pruefstand.yaml",
        work=tmp,
    )


def test_maintenance_posts_pending_and_runs_nothing(tmp_path: Path) -> None:
    (tmp_path / "MAINTENANCE").write_text("", encoding="utf-8")
    poster, calls = SpyPoster(), list[list[str]]()
    attempt = _attempt(tmp_path, poster, calls, tunnel_up=True)
    result = run_gate_job(attempt, health_sh=tmp_path / "health.sh", lock_dir=tmp_path)
    assert result == "not run (maintenance or busy)"
    assert poster.calls == [("post_status", SHA, "pending", MAINTENANCE, "pruefstand/gate")]
    assert calls == []


def test_a_tunnel_that_stays_down_is_an_unhealthy_error_and_no_run(tmp_path: Path) -> None:
    poster, calls = SpyPoster(), list[list[str]]()
    attempt = _attempt(tmp_path, poster, calls, tunnel_up=False)
    result = run_gate_job(attempt, health_sh=tmp_path / "health.sh", lock_dir=tmp_path)
    assert result == "error"
    assert poster.calls == [
        ("post_status", SHA, "error", "executor unhealthy: tunnel", "pruefstand/gate")
    ]
    assert not any(c[:2] == ["docker", "pull"] for c in calls)
    assert ["sudo", "-n", "systemctl", "restart", "pruefstand-tunnel"] in calls


def test_an_image_whose_revision_is_not_the_head_posts_error_and_never_starts_it(
    tmp_path: Path,
) -> None:
    poster, calls = SpyPoster(), list[list[str]]()
    attempt = _attempt(tmp_path, poster, calls, tunnel_up=True, label="c" * 40)
    result = run_gate_job(attempt, health_sh=tmp_path / "health.sh", lock_dir=tmp_path)
    assert result.startswith("error: image verification failed")
    assert poster.calls[-1][:3] == ("post_status", SHA, "error")
    assert "revision label" in poster.calls[-1][3]
    assert not any(c[:2] == ["docker", "run"] for c in calls)
