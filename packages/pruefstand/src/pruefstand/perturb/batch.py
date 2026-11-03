"""Resumable, quota-aware passes over many questions (ADR-0019: rewrite pass, then validate pass).

The rewrite pass talks to the GitHub Models free tier: it stores every draft in
``<dir>/rewrites.jsonl`` as soon as it exists, skips drafts that are already stored, and stops at
the daily quota (``QuotaExhausted``) or the request cap of the client's ``Budget``
(``BudgetExceeded``). The next run continues where it stopped. The validate pass reads the stored
drafts and runs the validity check, with no rewrite call.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, ValidationError

from pruefstand.core.errors import BudgetExceeded, DatasetError, LLMError, QuotaExhausted
from pruefstand.core.hashing import stable_hash
from pruefstand.core.logging import get_logger
from pruefstand.core.models.perturb import PerturbResult
from pruefstand.core.protocols import LLMClientLike
from pruefstand.perturb._common import nfc
from pruefstand.perturb.draft import Draft
from pruefstand.perturb.llm_base import LLMRewritePerturbation
from pruefstand.perturb.validate import Verdict

log = get_logger(__name__)
STORE_FILE = "rewrites.jsonl"


class Item(BaseModel):
    """One text to perturb (a case id and its question)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    text: str


class Entry(BaseModel):
    """One stored draft (``draft`` is None when the perturbation does not apply)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    item_id: str
    name: str
    draft: Draft | None


class Outcome(BaseModel):
    """Result of the validate pass for one item and perturbation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str
    name: str
    result: PerturbResult
    verdict: Verdict | None = None


class PassReport(BaseModel):
    """What a rewrite pass did; ``stopped`` is ``quota``, ``budget`` or None (finished)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    done: int
    skipped: int
    failed: int
    remaining: int
    stopped: Literal["quota", "budget"] | None = None


class RewriteStore:
    """Append-only JSON-lines store of drafts in ``directory``.

    Raises:
        DatasetError: A line of an existing file is not a valid entry.
    """

    def __init__(self, directory: Path) -> None:
        self._path = directory / STORE_FILE
        self._entries: dict[str, Entry] = {}
        if self._path.is_file():
            for number, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), 1):
                if line.strip():
                    entry = self._parse(line, number)
                    self._entries[entry.key] = entry

    def _parse(self, line: str, number: int) -> Entry:
        try:
            return Entry.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValidationError) as err:
            msg = f"{self._path.name}:{number} is not a valid rewrite entry"
            raise DatasetError(msg) from err

    def get(self, key: str) -> Entry | None:
        """Return the entry stored under ``key``."""
        return self._entries.get(key)

    def entries(self) -> tuple[Entry, ...]:
        """Return all entries in storage order."""
        return tuple(self._entries.values())

    def put(self, entry: Entry) -> None:
        """Append ``entry`` to the file (flushed at once) and remember it."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n")
        self._entries[entry.key] = entry


def entry_key(item: Item, p: LLMRewritePerturbation, seed: int) -> str:
    """Return the store key: item, text, perturbation, prompt version, rewrite model, seed."""
    return stable_hash(item.id, nfc(item.text), p.name, p.version, p.rewriter.model, seed)


def item_rng(item: Item, p: LLMRewritePerturbation, seed: int) -> np.random.Generator:
    """Return the generator of one item and perturbation (same seed, same draw)."""
    return np.random.default_rng(int(stable_hash("rng", seed, item.id, p.name), 16))


async def rewrite_pass(
    items: Sequence[Item],
    perturbations: Sequence[LLMRewritePerturbation],
    *,
    llm: LLMClientLike,
    store: RewriteStore,
    seed: int = 0,
) -> PassReport:
    """Write the missing drafts; stop at the daily quota or the request cap.

    Args:
        items: Texts to perturb.
        perturbations: LLM-assisted perturbations.
        llm: Client of the rewrite model (its ``Budget`` carries ``--max-requests``).
        store: Where drafts are kept.
        seed: Seed of the per-item randomness.

    Returns:
        Counts of drafts written, skipped (already stored), failed (retried on the next run) and
        not yet attempted.

    Raises:
        PolicyViolation: The data guard blocked a call and the rewriter has no local model.
    """
    done = skipped = failed = 0
    total = len(items) * len(perturbations)
    for item in items:
        for p in perturbations:
            key = entry_key(item, p, seed)
            if store.get(key) is not None:
                skipped += 1
                continue
            try:
                draft = await p.adraft(nfc(item.text), llm, item_rng(item, p, seed))
            except QuotaExhausted:
                return _report(done, skipped, failed, total, "quota")
            except BudgetExceeded:
                return _report(done, skipped, failed, total, "budget")
            except LLMError as err:
                failed += 1
                log.warning(
                    "perturb_rewrite_failed", item=item.id, name=p.name, error=str(err)[:200]
                )
                continue
            if draft is not None:
                draft = draft.model_copy(update={"text": nfc(draft.text)})
            store.put(Entry(key=key, item_id=item.id, name=p.name, draft=draft))
            done += 1
    return _report(done, skipped, failed, total, None)


def _report(
    done: int, skipped: int, failed: int, total: int, stopped: Literal["quota", "budget"] | None
) -> PassReport:
    remaining = total - done - skipped - failed
    return PassReport(
        done=done, skipped=skipped, failed=failed, remaining=remaining, stopped=stopped
    )


async def validate_pass(
    items: Sequence[Item],
    perturbations: Sequence[LLMRewritePerturbation],
    *,
    store: RewriteStore,
    seed: int = 0,
) -> list[Outcome]:
    """Run the validity check on the stored drafts (no rewrite call).

    Args:
        items: The texts of the rewrite pass.
        perturbations: The same perturbations (they hold the validator).
        store: The drafts.
        seed: The seed of the rewrite pass.

    Returns:
        One outcome per stored draft, in item order; items without a stored draft are skipped.

    Raises:
        ConfigError: No validator, or none of another family than the rewriter.
        LLMError: An equivalence call failed.
    """
    outcomes: list[Outcome] = []
    for item in items:
        source = nfc(item.text)
        for p in perturbations:
            entry = store.get(entry_key(item, p, seed))
            if entry is None:
                continue
            verdict = await p.acheck(source, entry.draft) if entry.draft else None
            result = p.result(source, entry.draft, verdict)
            outcomes.append(Outcome(item_id=item.id, name=p.name, result=result, verdict=verdict))
    return outcomes
