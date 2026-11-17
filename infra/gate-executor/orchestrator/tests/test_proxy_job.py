"""llm-proxy per attempt (D206, ADR-0018, D1029): catalogue policy, no judges, lifecycle."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
import yaml
from gate_orchestrator.gate_job import Attempt
from gate_orchestrator.infra import InfraError
from gate_orchestrator.models import Job
from gate_orchestrator.proxy_job import (
    COMPOSE,
    down_argv,
    llm_proxy,
    policy_json,
    run_models,
    up_argv,
)
from llm_proxy import policy_from_json
from orch_testkit import SpyPoster

REPO = Path(__file__).resolve().parents[4]
CATALOGUE = yaml.safe_load((REPO / "infra/gpu/models.yaml").read_text(encoding="utf-8"))
SHA = "a" * 40


def test_the_policy_holds_mains_generator_and_embedder_and_the_proxy_accepts_it() -> None:
    ids = run_models(REPO)
    rag = yaml.safe_load((REPO / "apps/rag-demo/configs/rag.gpu.yaml").read_text(encoding="utf-8"))
    assert ids == [rag["generator"]["catalogue_id"], rag["embed"]["catalogue_id"]]
    policy = policy_from_json(policy_json(CATALOGUE, ids))  # the proxy's own parser
    by_id = {m["id"]: m for m in CATALOGUE["models"]}
    assert set(policy) == {by_id[i]["tag"] for i in ids}
    for model_id in ids:
        assert policy[by_id[model_id]["tag"]].num_ctx == by_id[model_id]["options"]["num_ctx"]


@pytest.mark.parametrize(
    ("ids", "match"),
    [
        (["ollama/gemma3:12b"], "role judge"),
        (["ollama/nope:1b"], "not in infra/gpu/models.yaml"),
    ],
)
def test_judges_and_unknown_models_are_refused(ids: list[str], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        policy_json(CATALOGUE, ids)


def test_an_entry_without_num_ctx_is_refused() -> None:
    entry = {"id": "ollama/x", "tag": "x", "role": "generator", "options": {"seed": 1}}
    with pytest.raises(ValueError, match="num_ctx"):
        policy_json({"models": [entry]}, ["ollama/x"])


def test_compose_commands_target_only_llm_proxy() -> None:
    assert up_argv()[-4:] == ["up", "-d", "--wait", "llm-proxy"]
    assert down_argv()[-3:] == ["rm", "-sf", "llm-proxy"]
    assert COMPOSE.name == "compose.executor.yml"
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    assert "llm-proxy" in services


class Host:
    """Scripted docker host; records calls and the env of the compose up."""

    def __init__(self, *, up: int = 0, run: int = 0) -> None:
        self.up, self.run_exit = up, run
        self.calls: list[list[str]] = []
        self.up_env: Mapping[str, str] = {}

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        args = list(argv)
        self.calls.append(args)
        if args[:2] == ["docker", "compose"] and "up" in args:
            self.up_env = env
            return self.up, ""
        if args[:3] == ["docker", "image", "inspect"]:
            return 0, json.dumps({"org.opencontainers.image.revision": SHA})
        if args[:2] == ["docker", "run"]:
            return self.run_exit, ""
        return 0, ""

    def index(self, *prefix: str) -> int:
        return next(i for i, c in enumerate(self.calls) if c[: len(prefix)] == list(prefix))


def _attempt(tmp: Path, host: Host) -> Attempt:
    return Attempt(
        job=Job(kind="gate", sha=SHA, pr_number=7, tier="pr"),
        digest="sha256:" + "b" * 64,
        run=host,
        poster=SpyPoster(),
        statuses=lambda _sha: [],
        main_config=REPO / "pruefstand.yaml",
        work=tmp,
        env={"PATH": "/usr/bin"},
    )


def test_the_proxy_starts_before_the_candidate_and_is_removed_after_it(tmp_path: Path) -> None:
    host = Host(run=125)  # the candidate fails to start: the proxy must still be removed
    with pytest.raises(InfraError, match="candidate_down"):
        _attempt(tmp_path, host)(1)
    up = host.index("docker", "compose", "-f", str(COMPOSE), "up")
    assert up < host.index("docker", "run")
    assert host.index("docker", "rm", "-f") < host.index(
        "docker", "compose", "-f", str(COMPOSE), "rm"
    )
    assert json.loads(host.up_env["LLM_PROXY_POLICY"])


def test_a_proxy_that_does_not_come_up_stops_the_attempt_before_the_candidate(
    tmp_path: Path,
) -> None:
    host = Host(up=1)
    with pytest.raises(InfraError, match="proxy_down"):
        _attempt(tmp_path, host)(1)
    assert not any(c[:2] == ["docker", "run"] for c in host.calls)
    assert host.calls[-1][-3:] == ["rm", "-sf", "llm-proxy"]


def test_a_broken_catalogue_is_an_infra_error_and_starts_nothing(tmp_path: Path) -> None:
    host = Host()
    with pytest.raises(InfraError, match="proxy_policy"), llm_proxy(host, {}, tmp_path / "no-main"):
        pass
    assert host.calls == []
