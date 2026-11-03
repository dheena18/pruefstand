"""Checks of the pinned catalogue ``infra/gpu/models.yaml`` (S7).

Digests, ids, options, roles, provisional flags.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

HEX64 = re.compile(r"^[0-9a-f]{64}$")
OPTION_LIST = "num_ctx, num_predict, temperature, seed, top_p"
OPTION_KEYS = ("num_ctx", "num_predict", "temperature", "seed", "top_p")


def _entry_problems(m: Mapping[str, Any], *, require_final: bool) -> list[str]:
    name = str(m.get("id"))
    problems: list[str] = []
    if m.get("engine") == "ollama":
        if m.get("id") != "ollama/" + str(m.get("tag")):
            problems.append(f"{name}: id must be ollama/<tag>")
        if not HEX64.match(str(m.get("digest", ""))):
            problems.append(f"{name}: digest must be 64 hex characters")
        if sorted(m.get("options", {})) != sorted(OPTION_KEYS):
            problems.append(f"{name}: options must hold exactly {OPTION_LIST}")
    if require_final and m.get("provisional"):
        problems.append(f"{name}: still provisional")
    return problems


def pin_problems(models: Sequence[Mapping[str, Any]], *, require_final: bool) -> list[str]:
    """Return every violation of the pin rules (empty list = ok).

    Args:
        models: the ``models`` list of ``models.yaml``.
        require_final: also report entries that are still ``provisional: true``.
    """
    problems = [p for m in models for p in _entry_problems(m, require_final=require_final)]
    roles = [m.get("role") for m in models]
    judges = [m for m in models if m.get("role") == "judge"]
    if len(judges) != 1 or judges[0].get("family") != "gemma":
        problems.append("exactly one judge entry of family gemma is required (ADR-0019)")
    if not any(m.get("role") == "generator" and m.get("family") == "qwen" for m in models):
        problems.append("a generator entry of family qwen is required")
    problems += [
        f"role {r} is not allowed (ADR-0019)" for r in roles if r in {"nightly_judge", "large"}
    ]
    return problems
