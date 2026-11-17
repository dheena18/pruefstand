"""The shared index ``chunks_active`` in the executor Qdrant (T3.4, D1098, D1030).

Before an attempt serves a candidate, the orchestrator checks that the alias ``chunks_active``
exists (``GET /aliases`` with the read-write key on the loopback port). If it does, nothing is done
(idempotent). If not, it builds it once from the corpus the owner named in ``runner.env``
(``$PRUEFSTAND_DATA_ROOT/corpus/$PRUEFSTAND_CORPUS_VERSION``, the directory ``pruefstand ingest``
writes) with the trusted main's ``rag-demo index --encoder ollama`` under the held GPU lock;
``rag-demo index`` switches the alias when the collection is complete. The orchestrator cannot
know the corpus version on its own (it is not in any file it reads), hence the runner.env key.
"""

from collections.abc import Callable, Mapping
from pathlib import Path

import httpx

from gate_orchestrator.gate_run import Runner
from gate_orchestrator.infra import InfraError

ALIAS = "chunks_active"
LOOPBACK = "http://127.0.0.1:6333"
TIMEOUT_S = 10.0
Aliases = Callable[[Mapping[str, str]], set[str]]


def qdrant_aliases(env: Mapping[str, str]) -> set[str]:
    """Alias names of the executor Qdrant (read-write key, loopback).

    Raises:
        InfraError: Qdrant is unreachable or refuses the key (``index_unavailable``).
    """
    url = env.get("QDRANT_URL") or LOOPBACK
    headers = {"api-key": env["QDRANT_API_KEY"]} if env.get("QDRANT_API_KEY") else {}
    try:
        response = httpx.get(f"{url}/aliases", headers=headers, timeout=TIMEOUT_S)
    except httpx.HTTPError as exc:
        msg = f"index_unavailable: qdrant at {url}: {type(exc).__name__}"
        raise InfraError(msg) from None
    if not response.is_success:
        msg = f"index_unavailable: qdrant /aliases HTTP {response.status_code}"
        raise InfraError(msg)
    try:
        aliases = response.json()["result"]["aliases"]
        return {str(a["alias_name"]) for a in aliases}
    except (ValueError, KeyError, TypeError) as exc:  # stay on the infra retry path (review #259)
        msg = "index_unavailable: qdrant /aliases answer is not an alias list"
        raise InfraError(msg) from exc


def corpus_dir(env: Mapping[str, str]) -> Path:
    """``$PRUEFSTAND_DATA_ROOT/corpus/$PRUEFSTAND_CORPUS_VERSION``.

    Raises:
        InfraError: either variable is unset or the directory does not exist (``index_missing``).
    """
    root, version = env.get("PRUEFSTAND_DATA_ROOT", ""), env.get("PRUEFSTAND_CORPUS_VERSION", "")
    corpus = Path(root) / "corpus"
    path = corpus / version
    plain = bool(root) and version not in {"", ".", ".."} and "/" not in version
    if not plain or path.resolve().parent != corpus.resolve() or not path.is_dir():
        msg = (
            f"index_missing: {ALIAS} is absent and no corpus to build it from "
            "(set PRUEFSTAND_CORPUS_VERSION in runner.env to a directory under <data root>/corpus/)"
        )
        raise InfraError(msg)
    return path


def ensure_shared_index(run: Runner, env: Mapping[str, str], aliases: Aliases) -> bool:
    """Make sure ``chunks_active`` exists; returns True when it had to be built.

    Raises:
        InfraError: Qdrant unavailable, no corpus, ``rag-demo index`` failed, or the alias is still
            missing afterwards.
    """
    if ALIAS in aliases(env):
        return False
    corpus = corpus_dir(env)
    tunnel = env.get("OLLAMA_GPU0_URL", "")
    if not tunnel:
        msg = "index_unavailable: OLLAMA_GPU0_URL (the tunnel) is unset, nothing to embed with"
        raise InfraError(msg)
    argv = ["rag-demo", "index", "--corpus", str(corpus), "--encoder", "ollama"]
    # rag.gpu.yaml embeds through endpoint_env LLM_PROXY_URL (D1081); this trusted host call goes
    # straight to the tunnel, like the owner's `make index` (review #259; llm-proxy is not up yet
    # and its name resolves only on gate-net)
    index_env = {**env, "QDRANT_URL": env.get("QDRANT_URL") or LOOPBACK, "LLM_PROXY_URL": tunnel}
    code, _ = run(argv, index_env)
    if code != 0:
        msg = f"index_failed: rag-demo index exit {code}"
        raise InfraError(msg)
    if ALIAS not in aliases(env):
        msg = f"index_failed: {ALIAS} still missing after rag-demo index"
        raise InfraError(msg)
    return True
