"""One tier-2 gate attempt for a PR job (X2.1, X2.4, X3.15, D206, D1095): commands only.

Under the held GPU lock and after the preflight: pull the signed candidate image by digest and
verify it (:func:`verify_image`), start it in the sandbox (:func:`candidate_argv`) on ``gate-net``,
wait for ``/v1/health``, run ``pruefstand run --tier pr`` against it with the trusted ``main`` gate
config (target URL replaced), gate against ref ``main`` and post the result. The candidate is
removed in every case. Commands go through the injected :data:`Runner`; the real stack is
exercised by the ``[GPU]`` dispatch drill, the argv builders here are unit-tested.
"""

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
CANDIDATE_PORT = 8000
CANDIDATE_CONFIG = "/app/configs/rag.gpu.yaml"
SHARED_COLLECTION = "chunks_active"
QDRANT_URL = "http://qdrant:6333"
Runner = Callable[[Sequence[str], Mapping[str, str]], tuple[int, str]]


def digest_from_status(status: Mapping[str, object] | None) -> str | None:
    """The ``sha256:<64 hex>`` the ``pruefstand/image`` status names (description or target URL)."""
    if status is None or status.get("state") != "success":
        return None
    for key in ("description", "target_url"):
        match = DIGEST.search(str(status.get(key) or ""))
        if match:
            return match.group(0)
    return None


def candidate_env(env: Mapping[str, str]) -> dict[str, str]:
    """Values the candidate gets by name (the allow-list of ``candidate.ALLOWED_ENV``)."""
    out = {
        "RAG_CONFIG": CANDIDATE_CONFIG,
        "QDRANT_URL": QDRANT_URL,
        "RAG_COLLECTION": SHARED_COLLECTION,
    }
    for name in ("QDRANT_API_KEY", "PRUEFSTAND_CANDIDATE_API_KEY"):
        if env.get(name):
            out[name] = env[name]
    return out


def ip_argv(name: str) -> list[str]:
    """``docker inspect`` argv printing the candidate's address on ``gate-net``."""
    fmt = '{{(index .NetworkSettings.Networks "gate-net").IPAddress}}'
    return ["docker", "inspect", "--format", fmt, name]


def run_config(main_config: Path, out: Path, target_url: str) -> Path:
    """Copy the trusted ``main`` gate config with ``target.url`` set to the candidate."""
    data = yaml.safe_load(main_config.read_text(encoding="utf-8"))
    data.setdefault("target", {})["url"] = target_url
    out.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out


def pruefstand_run_argv(config: Path, runs: Path, *, judged_subset: bool) -> list[str]:
    """``pruefstand run --tier pr`` (the PR budget rule may add ``--judged-subset``, D199)."""
    argv = ["pruefstand", "run", "--config", str(config), "--tier", "pr", "--out", str(runs)]
    return [*argv, "--judged-subset"] if judged_subset else argv


def gate_argv(run_dir: Path, config: Path) -> list[str]:
    """``pruefstand gate`` of the candidate run against the stored ``main`` baseline."""
    return [
        "pruefstand", "gate", "--candidate", str(run_dir), "--from-store", "--ref", "main",
        "--config", str(config),
    ]  # fmt: skip


@dataclass(frozen=True)
class GateOutcome:
    """What a finished gate attempt produced (read from ``gate.json`` / ``run.json``)."""

    status: str
    summary: str
    no_baseline: bool
    infra_error: str | None


def read_outcome(run_dir: Path) -> GateOutcome:
    """Parse ``gate.json`` and ``run.json`` of a run directory.

    Raises:
        ValueError: ``gate.json`` is missing or not a gate report.
    """
    gate = json.loads((run_dir / "gate.json").read_text(encoding="utf-8"))
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    status = gate.get("status")
    if not isinstance(status, str):
        msg = f"{run_dir}/gate.json has no status"
        raise ValueError(msg)  # noqa: TRY004  (a malformed file, not a caller's type error)
    infra = run.get("infra_error")  # run.json is the RunManifest
    no_baseline = bool(gate.get("no_baseline"))
    summary = gate.get("eval_fingerprint") if no_baseline else gate.get("candidate_run_id")
    return GateOutcome(
        status=status,
        summary=str(summary or status),
        no_baseline=no_baseline,
        infra_error=str(infra) if infra else None,
    )
