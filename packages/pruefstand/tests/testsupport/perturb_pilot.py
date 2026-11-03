"""Shared setup of the recorded / live perturbation tests (T4.5): pilot questions, cassette dirs.

The model ids come from the environment (``PRUEFSTAND_PERTURB_REWRITE_MODEL`` = the pinned
GitHub Models datagen model, ``PRUEFSTAND_PERTURB_JUDGE_MODEL`` = the local judge) and are stored
in ``meta.json`` next to the cassettes, so a replay needs no environment.
"""

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.protocols import LLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder
from pruefstand.perturb.llm_base import LLMRewritePerturbation
from pruefstand.perturb.llm_registry import build_llm_perturbation, llm_perturbation_names
from pruefstand.perturb.rewriter import Rewriter
from pruefstand.perturb.validate import RewriteValidator

REPO = Path(__file__).resolve().parents[3]
QUESTIONS_FILE = REPO / "datasets" / "fixtures" / "perturb_pilot_questions.txt"
CASSETTES = Path(__file__).resolve().parents[1] / "cassettes" / "perturb"
RECORDED = 8  # the first questions of the pilot file are recorded as cassettes
REWRITE_ENV = "PRUEFSTAND_PERTURB_REWRITE_MODEL"
JUDGE_ENV = "PRUEFSTAND_PERTURB_JUDGE_MODEL"


class Meta(BaseModel):
    """Models behind a cassette set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rewrite_model: str
    judge_model: str


def questions() -> list[str]:
    """Return the pilot questions."""
    lines = QUESTIONS_FILE.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def env_meta() -> Meta | None:
    """Return the models named in the environment, or None when one is missing."""
    rewrite, judge = os.environ.get(REWRITE_ENV), os.environ.get(JUDGE_ENV)
    return Meta(rewrite_model=rewrite, judge_model=judge) if rewrite and judge else None


def load_meta() -> Meta | None:
    """Return ``meta.json`` of the recorded cassettes, or None when nothing was recorded."""
    path = CASSETTES / "meta.json"
    return Meta.model_validate(json.loads(path.read_text("utf-8"))) if path.is_file() else None


def _client(backend: LLMBackend) -> LLMClient:
    return LLMClient(
        backend,
        None,
        Budget(max_usd=None, max_tokens=None),
        CallRecorder(),
        LLMPolicy(LLMPolicyConfig(), CanaryRegistry(canaries=())),
    )


def build(
    meta: Meta, rewrite_backend: LLMBackend, judge_backend: LLMBackend
) -> tuple[list[LLMRewritePerturbation], LLMClient]:
    """Return the four perturbations and the rewrite client."""
    validator = RewriteValidator(_client(judge_backend), meta.judge_model)
    rewriter = Rewriter(meta.rewrite_model)
    perturbations = [
        build_llm_perturbation(n, rewriter, validator) for n in llm_perturbation_names()
    ]
    return perturbations, _client(rewrite_backend)
