"""``docker run`` argv of the untrusted candidate (S6; D206, D242, X2.5, security.md C2/C18).

Sandbox: no GPU or devices, ``--read-only``, ``--cap-drop ALL``, ``no-new-privileges``, a non-root
user, cpu/memory/pids limits, ``--shm-size 2g``, only the ``--internal`` network ``gate-net``
(never ``proxy-egress``, never the host network), no published port, no ``--add-host``, no Docker
socket, no held-out canary mount or env. Its only routes: ``LLM_PROXY_URL=http://llm-proxy:11500``,
``RERANK_URL=http://rerank-cpu:8201`` and Qdrant on ``gate-net``. The env is an explicit allow-list.
"""

from collections.abc import Mapping

LLM_PROXY_URL = "http://llm-proxy:11500"
RERANK_URL = "http://rerank-cpu:8201"
NETWORK = "gate-net"
USER = "10001:10001"
ALLOWED_ENV = frozenset(
    {"PRUEFSTAND_CANDIDATE_API_KEY", "QDRANT_URL", "QDRANT_API_KEY", "RAG_COLLECTION", "RAG_CONFIG"}
)


def candidate_argv(
    image_ref: str, *, name: str, job_label: str, env: Mapping[str, str]
) -> list[str]:
    """``docker run`` argv for one candidate container.

    Args:
        image_ref: the verified, digest-pinned image.
        name: container name.
        job_label: value of the ``pruefstand.job`` label (cleaned up by the job hooks).
        env: extra env; only the names in ``ALLOWED_ENV`` are accepted. Values are passed by name
            (``--env NAME``), so secrets never appear in the argv.

    Returns:
        The argv.

    Raises:
        ValueError: ``env`` names a variable outside the allow-list or the image is not pinned.
    """
    extra = sorted(set(env) - ALLOWED_ENV)
    if extra:
        msg = f"candidate env not allowed: {', '.join(extra)}"
        raise ValueError(msg)
    if "@sha256:" not in image_ref:
        msg = "candidate image must be pinned by digest"
        raise ValueError(msg)
    argv = [
        "docker", "run", "--detach", "--name", name,
        "--label", f"pruefstand.job={job_label}",
        "--network", NETWORK,
        "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",  # noqa: S108 - in-container tmpfs
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", USER, "--pids-limit", "512", "--cpus", "4", "--memory", "8g", "--shm-size", "2g",
        "--env", f"LLM_PROXY_URL={LLM_PROXY_URL}", "--env", f"RERANK_URL={RERANK_URL}",
    ]  # fmt: skip
    for key in sorted(env):
        argv += ["--env", key]
    return [*argv, image_ref]
