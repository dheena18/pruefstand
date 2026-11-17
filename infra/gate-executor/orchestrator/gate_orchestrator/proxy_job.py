"""``llm-proxy`` for one gate attempt (D206, D242, ADR-0018, D1029).

The orchestrator writes ``LLM_PROXY_POLICY`` (``{tag: catalogue fields}``) for exactly the
generator and embedding models that main's ``apps/rag-demo/configs/rag.gpu.yaml`` names, read from
the trusted ``infra/gpu/models.yaml`` of the pinned main worktree; a judge, an unknown model or an
entry without ``num_ctx`` is refused before anything starts. It then brings up the ``llm-proxy``
service of ``compose.executor.yml`` (``gate-net`` + ``proxy-egress``; the candidate reaches it as
``http://llm-proxy:11500``) and waits for it to be healthy, and removes it again in every case.
"""

import json
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

import yaml

from gate_orchestrator.gate_run import Runner
from gate_orchestrator.infra import InfraError

COMPOSE = Path(__file__).resolve().parents[2] / "compose.executor.yml"
FORWARD_ROLES = frozenset({"generator", "embed"})
SECTIONS = {"generator": "generator", "embed": "embed"}


def _yaml(path: Path) -> Mapping[str, object]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, Mapping) else {}


def run_models(main_dir: Path) -> list[str]:
    """Catalogue ids of the generator and embedding model of main's ``rag.gpu.yaml``.

    Raises:
        ValueError: a section has no ``catalogue_id``.
    """
    rag = _yaml(main_dir / "apps" / "rag-demo" / "configs" / "rag.gpu.yaml")
    ids = []
    for section in SECTIONS.values():
        block = rag.get(section)
        model = block.get("catalogue_id") if isinstance(block, Mapping) else None
        if isinstance(model, str):
            ids.append(model)
            continue
        msg = f"rag.gpu.yaml: {section}.catalogue_id missing"
        raise ValueError(msg)
    return ids


def policy_json(catalogue: Mapping[str, object], model_ids: list[str]) -> str:
    """``LLM_PROXY_POLICY`` for ``model_ids``: ``{tag: entry}`` of generator/embed entries only.

    Raises:
        ValueError: a model is not in the catalogue, is a judge (ADR-0018) or lacks ``num_ctx``.
    """
    models = catalogue.get("models")
    by_id = {
        str(m.get("id")): m
        for m in (models if isinstance(models, list) else [])
        if isinstance(m, Mapping)
    }
    policy: dict[str, dict[str, object]] = {}
    for model_id in model_ids:
        entry = by_id.get(model_id)
        if entry is None:
            msg = f"{model_id} is not in infra/gpu/models.yaml"
            raise ValueError(msg)
        if entry.get("role") not in FORWARD_ROLES:
            role = entry.get("role")
            msg = f"{model_id} has role {role}; llm-proxy forwards generator and embed only"
            raise ValueError(msg)
        options = entry.get("options")
        num_ctx = options.get("num_ctx") if isinstance(options, Mapping) else None
        if num_ctx is None or isinstance(num_ctx, bool) or not isinstance(num_ctx, int):
            msg = f"{model_id}: options need an integer num_ctx"
            raise ValueError(msg)
        fields = ("role", "family", "ollama_family", "options", "option_bounds")
        policy[str(entry["tag"])] = {k: entry[k] for k in fields if k in entry}
    return json.dumps(policy, sort_keys=True)


def up_argv(compose: Path = COMPOSE) -> list[str]:
    """``docker compose up -d --wait llm-proxy`` (healthy before the candidate starts)."""
    return ["docker", "compose", "-f", str(compose), "up", "-d", "--wait", "llm-proxy"]


def down_argv(compose: Path = COMPOSE) -> list[str]:
    """``docker compose rm -sf llm-proxy`` (stop and remove)."""
    return ["docker", "compose", "-f", str(compose), "rm", "-sf", "llm-proxy"]


@contextmanager
def llm_proxy(
    run: Runner, env: Mapping[str, str], main_dir: Path, compose: Path = COMPOSE
) -> Iterator[None]:
    """Serve ``llm-proxy`` for the body; always removed afterwards.

    Raises:
        InfraError: the policy cannot be built (``proxy_policy``), the proxy does not come up
            healthy (``proxy_down``) or cannot be removed (``proxy_cleanup``, only when the body
            itself succeeded).
    """
    try:
        policy = policy_json(
            _yaml(main_dir / "infra" / "gpu" / "models.yaml"), run_models(main_dir)
        )
    except (OSError, ValueError) as exc:
        msg = f"proxy_policy: {exc}"
        raise InfraError(msg) from exc
    # compose interpolates the whole file for every command, so the teardown needs the policy too
    penv = {**env, "LLM_PROXY_POLICY": policy}
    try:
        code, _ = run(up_argv(compose), penv)
        if code != 0:
            msg = f"proxy_down: llm-proxy did not come up healthy (exit {code})"
            raise InfraError(msg)
        yield
    finally:
        down, _ = run(down_argv(compose), penv)
        if down != 0 and sys.exc_info()[1] is None:  # never hide the attempt's own error
            msg = f"proxy_cleanup: docker compose rm llm-proxy exit {down}"
            raise InfraError(msg)
