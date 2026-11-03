"""Per-release canary rotation and the retired list (T4.6 S6, D93).

The maintainer rotates in a release-prep PR before every dataset release from v2 on: new tokens and
facts are issued for the next release (and planted again with ``plant_canaries``), and the old ones
are appended to ``datasets/canaries/retired.json`` once the release upload succeeded (T9.1b's
``retired-json`` artefact). Retired tokens stay forbidden: leak checks use current and retired
tokens. ``dataset-release.yml`` only checks the file, it never writes it.
"""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from pruefstand.attacks.canary import make_canary_token
from pruefstand.attacks.facts import make_semantic_fact, template_index_of
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.attacks import Canary, CanaryRegistry

_SEED_BITS = 32
_TEMPLATES = 12


class RetiredCanary(BaseModel):
    """One entry of ``datasets/canaries/retired.json``.

    ``probe_question`` and ``forbidden_answer`` are additions to the documented
    ``{token, tenant, fact, retired_in}``: the contamination probe needs them to ask the model
    closed-book and to recognise the answer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    token: str
    tenant: str
    fact: str | None
    retired_in: str
    probe_question: str | None = None
    forbidden_answer: str | None = None


def _rotate_one(
    canary: Canary, rng: np.random.Generator, used: set[str], values: set[str]
) -> Canary:
    if canary.kind == "token":
        token = make_canary_token(canary.tenant, rng)
        while token in used:
            token = make_canary_token(canary.tenant, rng)
        used.add(token)
        return canary.model_copy(update={"token": token, "forbidden_answer": token})
    index = template_index_of(canary.tenant, canary.fact or "")
    fact = make_semantic_fact(
        canary.tenant, int(rng.integers(0, _TEMPLATES)) if index is None else index, rng, values
    )
    values.add(fact.value)
    return canary.model_copy(
        update={
            "token": fact.value, "fact": fact.sentence, "probe_question": fact.probe_question,
            "forbidden_answer": fact.forbidden_answer,
        }
    )  # fmt: skip


def rotate_canaries(
    registry: CanaryRegistry, release: str, rng: np.random.Generator
) -> tuple[CanaryRegistry, list[Canary]]:
    """Issue new tokens and facts for ``release``; the old canaries are returned as retired.

    Args:
        registry: The current canaries.
        release: The next dataset release, for example ``"v2"``; mixed into the seed, so the same
            ``rng`` seed gives other canaries for another release.
        rng: Seeded generator.

    Returns:
        The new registry (same tenants, documents and kinds, in the same order; every token and
        every semantic value is new) and the old canaries, to be appended to ``retired.json``
        after the upload (``retire``).

    Raises:
        DatasetError: ``release`` is blank, or a tenant has no canary prefix or fact templates.
    """
    if not release.strip():
        msg = "rotate_canaries needs a release name (for example 'v2')"
        raise DatasetError(msg)
    salt = int.from_bytes(hashlib.sha256(release.strip().encode("utf-8")).digest()[:4], "big")
    child = np.random.default_rng([int(rng.integers(0, 1 << _SEED_BITS)), salt])
    used = {c.token for c in registry.canaries}
    values = {c.token for c in registry.canaries if c.kind == "semantic"}
    new = tuple(_rotate_one(c, child, used, values) for c in registry.canaries)
    return CanaryRegistry(canaries=new), list(registry.canaries)


_ADAPTER = TypeAdapter(list[RetiredCanary])


def load_retired(path: Path) -> list[RetiredCanary]:
    """Read ``retired.json``.

    Args:
        path: The file (a JSON list; ``[]`` in v1).

    Returns:
        The retired canaries in file order.

    Raises:
        DatasetError: The file is missing, not JSON or not a list of retired canaries.
    """
    try:
        return _ADAPTER.validate_json(path.read_bytes())
    except (OSError, ValidationError) as exc:
        msg = f"retired canaries file {path.name} is unreadable or malformed: {type(exc).__name__}"
        raise DatasetError(msg) from exc


def retire(path: Path, canaries: Iterable[Canary], retired_in: str) -> list[RetiredCanary]:
    """Append canaries to ``retired.json`` (those already listed are skipped).

    Args:
        path: The file; created as ``[]`` when missing.
        canaries: Canaries that left the registry (the second result of ``rotate_canaries``).
        retired_in: The release that retired them, for example ``"v1"``.

    Returns:
        The entries added.

    Raises:
        DatasetError: The existing file is malformed.
    """
    current = load_retired(path) if path.exists() else []
    known = {(r.token, r.tenant) for r in current}
    added: list[RetiredCanary] = []
    for canary in canaries:
        if (canary.token, canary.tenant) in known:
            continue
        known.add((canary.token, canary.tenant))
        added.append(
            RetiredCanary(
                token=canary.token,
                tenant=canary.tenant,
                fact=canary.fact,
                retired_in=retired_in,
                probe_question=canary.probe_question,
                forbidden_answer=canary.forbidden_answer,
            )
        )
    rows = [r.model_dump(mode="json") for r in [*current, *added]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return added
