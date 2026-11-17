"""A whole gate attempt through the real control flow (review #224): lock, preflight, retry,
result posted only on change, the candidate always removed, the read-only Qdrant key only."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from gate_orchestrator.gate_job import Attempt, run_gate_job
from gate_orchestrator.models import Job
from orch_testkit import SpyPoster

from pruefstand.core.enums import GateStatus
from pruefstand.report.github import status_for

SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64
MAIN_CONFIG = Path(__file__).resolve().parents[4] / "pruefstand.yaml"
ENV = {"QDRANT_API_KEY": "rw-key", "QDRANT_READ_ONLY_API_KEY": "ro-key", "PATH": "/usr/bin"}


@dataclass
class Host:
    """Scripted answers of the commands one attempt runs (docker, cosign, pruefstand, health.sh)."""

    tmp: Path
    infra_errors: list[str | None]
    write_gate: bool = True
    calls: list[list[str]] = field(default_factory=list)
    envs: dict[str, Mapping[str, str]] = field(default_factory=dict)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        args = list(argv)
        self.calls.append(args)
        if args[:3] == ["docker", "image", "inspect"]:
            return 0, json.dumps({"org.opencontainers.image.revision": SHA})
        if args[:2] == ["docker", "run"]:
            self.envs["docker run"] = env
        if args[:2] == ["docker", "inspect"]:
            return 0, "10.231.0.5\n"
        if args[:2] == ["pruefstand", "run"]:
            return 0, f"log line\n{self._run_dir()}\n"
        return 0, ""

    def _run_dir(self) -> Path:
        run = self.tmp / f"run{len([c for c in self.calls if c[:2] == ['pruefstand', 'run']])}"
        run.mkdir()
        infra = self.infra_errors.pop(0)
        (run / "run.json").write_text(json.dumps({"infra_error": infra}), encoding="utf-8")
        if self.write_gate:
            gate = {"status": "pass", "candidate_run_id": run.name, "no_baseline": False}
            (run / "gate.json").write_text(json.dumps(gate), encoding="utf-8")
        return run

    def count(self, *prefix: str) -> int:
        return sum(c[: len(prefix)] == list(prefix) for c in self.calls)


def _job(tmp: Path, host: Host, poster: SpyPoster, current: list[dict[str, object]]) -> str:
    attempt = Attempt(
        job=Job(kind="gate", sha=SHA, pr_number=7, tier="pr"),
        digest=DIGEST,
        run=host,
        poster=poster,
        statuses=lambda _sha: current,
        main_config=MAIN_CONFIG,
        work=tmp,
        env=ENV,
    )
    return run_gate_job(attempt, health_sh=tmp / "health.sh", lock_dir=tmp)


def test_a_clean_attempt_posts_the_result_once_and_removes_the_candidate(tmp_path: Path) -> None:
    host, poster = Host(tmp_path, [None]), SpyPoster()
    assert _job(tmp_path, host, poster, []) == "pass"
    assert [c[0] for c in poster.calls] == ["set_check"]
    assert poster.calls[0][2] == str(GateStatus.PASS)
    order = [c[:2] for c in host.calls if c[0] in {"docker", "cosign", "pruefstand"}]
    assert order.index(["cosign", "verify"]) < order.index(["docker", "run"])
    assert order.index(["docker", "run"]) < order.index(["pruefstand", "run"])
    assert host.count("docker", "rm", "-f") == 1
    assert host.count("bash", str(tmp_path / "health.sh"), "--repair") == 1  # the preflight only


def test_an_unchanged_result_is_not_posted_again(tmp_path: Path) -> None:
    state, description = status_for(GateStatus.PASS, "run1", no_baseline=False, infra_error=False)
    current: list[dict[str, object]] = [
        {"context": "pruefstand/gate", "state": state, "description": description}
    ]
    host, poster = Host(tmp_path, [None]), SpyPoster()
    _job(tmp_path, host, poster, current)
    assert poster.calls == []


def test_an_infra_error_repairs_once_retries_and_posts_one_final_result(tmp_path: Path) -> None:
    host, poster = Host(tmp_path, ["ollama_down: gpu0", None]), SpyPoster()
    assert _job(tmp_path, host, poster, []) == "pass"
    assert [c[0] for c in poster.calls] == ["set_check", "set_check"]
    assert poster.calls[0][5] == "True"  # the infra error ("retrying once")
    assert "retrying once" in poster.calls[0][3]
    assert poster.calls[1][2] == str(GateStatus.PASS)
    assert host.count("bash", str(tmp_path / "health.sh"), "--repair") == 2  # preflight + repair
    assert host.count("pruefstand", "run") == 2
    assert host.count("docker", "rm", "-f") == 2


def test_a_missing_gate_json_is_an_infra_error_with_a_status(tmp_path: Path) -> None:
    host, poster = Host(tmp_path, [None, None], write_gate=False), SpyPoster()
    result = _job(tmp_path, host, poster, [])
    assert result.startswith("error: gate_failed")
    assert all(c[5] == "True" for c in poster.calls)
    assert "re-dispatch to retry" in poster.calls[-1][3]
    assert host.count("docker", "rm", "-f") == 2


def test_the_candidate_gets_only_the_read_only_qdrant_key(tmp_path: Path) -> None:
    host = Host(tmp_path, [None])
    _job(tmp_path, host, SpyPoster(), [])
    env = host.envs["docker run"]
    assert env["QDRANT_API_KEY"] == "ro-key"
    assert "rw-key" not in env.values()
    run = next(c for c in host.calls if c[:2] == ["docker", "run"])
    assert "rw-key" not in run
    assert "ro-key" not in run  # passed by name, never on the command line


@pytest.mark.parametrize("digest", ["", "sha256:short"])
def test_an_image_status_without_digest_is_refused_up_front(tmp_path: Path, digest: str) -> None:
    host, poster = Host(tmp_path, []), SpyPoster()
    attempt = Attempt(
        job=Job(kind="gate", sha=SHA, pr_number=7, tier="pr"),
        digest=digest,
        run=host,
        poster=poster,
        statuses=lambda _sha: [],
        main_config=MAIN_CONFIG,
        work=tmp_path,
        env=ENV,
    )
    result = run_gate_job(attempt, health_sh=tmp_path / "health.sh", lock_dir=tmp_path)
    assert result == "error: image verification failed: image status has no digest"
    assert poster.calls[-1][2] == "error"
    assert host.count("docker", "pull") == 0
