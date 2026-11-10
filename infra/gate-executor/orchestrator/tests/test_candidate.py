"""Candidate sandbox argv (D206, D242, X2.5): what must and must never be in ``docker run``."""

import pytest
from gate_orchestrator.candidate import candidate_argv

REF = "ghcr.io/dheena18/rag-demo@sha256:" + "a" * 64
ENV = {
    "PRUEFSTAND_CANDIDATE_API_KEY": "x",
    "QDRANT_URL": "http://qdrant:6333",
    "RAG_COLLECTION": "pr_5_fffffff",
}
ARGV = candidate_argv(REF, name="cand-5", job_label="run-1", env=ENV)
TEXT = " ".join(ARGV)


@pytest.mark.parametrize(
    "required",
    [
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--pids-limit",
        "--network gate-net",
        "--user 10001:10001",
        "--env LLM_PROXY_URL=http://llm-proxy:11500",
        "--env RERANK_URL=http://rerank-cpu:8201",
        "--label pruefstand.job=run-1",
        "--shm-size 2g",
    ],
)
def test_sandbox_flags_present(required: str) -> None:
    assert required in TEXT


@pytest.mark.parametrize(
    "forbidden",
    [
        "--add-host",
        "host-gateway",
        "proxy-egress",
        "OLLAMA_GPU0_URL",
        "OLLAMA_GPU1_URL",
        "localhost:1143",
        "172.17.0.1",
        "--publish",
        "--gpus",
        "--device",
        "docker.sock",
        "--privileged",
        "--network host",
        "--network=host",
        "PRUEFSTAND_HELDOUT_DIR",
        "canaries",
        "--volume",
        "--mount",
        "--ipc",
    ],
)
def test_forbidden_flags_absent(forbidden: str) -> None:
    assert forbidden not in TEXT
    assert "-p" not in ARGV
    assert "-v" not in ARGV


def test_env_values_are_passed_by_name_only() -> None:
    assert "--env PRUEFSTAND_CANDIDATE_API_KEY" in TEXT
    assert "PRUEFSTAND_CANDIDATE_API_KEY=" not in TEXT
    assert ARGV[-1] == REF


@pytest.mark.parametrize(
    "name",
    ["PRUEFSTAND_HELDOUT_DIR", "OLLAMA_GPU1_URL", "DASHBOARD_DATA_PAT", "LLM_PROXY_UPSTREAM"],
)
def test_env_outside_the_allow_list_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match=name):
        candidate_argv(REF, name="c", job_label="j", env={name: "x"})


def test_unpinned_image_is_refused() -> None:
    with pytest.raises(ValueError, match="digest"):
        candidate_argv("ghcr.io/dheena18/rag-demo:latest", name="c", job_label="j", env={})
