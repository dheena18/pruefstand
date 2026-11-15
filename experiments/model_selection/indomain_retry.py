"""Per-item regeneration of the in-domain dev set (D1201): retry an invalid answer up to N times.

The D1200 benchmark found 35-45 % of first answers invalid (evidence span not verbatim or over
400 characters, JSON in fences). An item is therefore asked again, at most ``retries`` times
(default ``DEFAULT_RETRIES``), until one answer passes ``indomain_data.validate_item``. Every
attempt is one call against ``--max-calls`` and is cached under its own key (attempt 0 = the
passage id, so caches of earlier runs stay valid; attempt k = ``<id>#retry<k>``). Answers are
read back in attempt order, so a rerun continues exactly where a stopped batch ended.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from model_selection import indomain_data as data
from model_selection import indomain_gen as gen

DEFAULT_RETRIES = 2


def attempt_key(passage_id: str, attempt: int) -> str:
    """Cache key of attempt ``attempt`` (0 = the first call) of a passage.

    >>> attempt_key("gii-bgb-622", 0), attempt_key("gii-bgb-622", 2)
    ('gii-bgb-622', 'gii-bgb-622#retry2')
    """
    return passage_id if attempt == 0 else f"{passage_id}#retry{attempt}"


def judge_answer(text: str, passage_text: str) -> tuple[data.Item | None, str]:
    """(item, "") for a valid answer, else (None, reason); fenced JSON is tolerated."""
    try:
        raw = gen.parse_json_object(text)
    except gen.GenError:
        return None, "no_json"
    return data.validate_item(raw, passage_text)


def answers(model: str, passage_id: str, retries: int) -> list[str]:
    """The cached answers of attempts 0..retries, in order, up to the first missing one."""
    out: list[str] = []
    for attempt in range(retries + 1):
        text = gen.cached_response(model, data.GEN_PROMPT, attempt_key(passage_id, attempt))
        if text is None:
            break
        out.append(text)
    return out


def first_valid(texts: Sequence[str], passage_text: str) -> tuple[data.Item | None, str]:
    """The first valid answer of ``texts``; else (None, reason of the last one or not_generated)."""
    reason = "not_generated"
    for text in texts:
        item, reason = judge_answer(text, passage_text)
        if item is not None:
            return item, ""
    return None, reason


def next_attempt(texts: Sequence[str], passage_text: str, retries: int) -> int | None:
    """Index of the next attempt; None when an answer is valid or ``retries`` are used up."""
    if first_valid(texts, passage_text)[0] is not None or len(texts) > retries:
        return None
    return len(texts)


@dataclass
class Tally:
    """Calls made by one ``generate`` run: all calls, the retries among them, items left invalid."""

    calls: int = 0
    retries: int = 0
    exhausted: int = 0

    def line(self) -> str:
        """One summary line for the log."""
        return f"{self.calls} new calls ({self.retries} retries), {self.exhausted} items exhausted"


def run_generate(
    plan: Sequence[data.Passage],
    cached: Callable[[str], list[str]],
    call: Callable[[str, data.Passage], None],
    *,
    retries: int,
    max_calls: int,
    tally: Tally,
) -> Tally:
    """Ask each planned passage until an answer is valid, ``retries`` are used or the budget ends.

    ``cached(passage_id)`` returns the answers so far (``answers``); ``call(key, passage)`` makes
    and caches one call. ``tally`` is updated in place, so a quota stop inside ``call`` still
    leaves the counts of the calls made.
    """
    for p in plan:
        while tally.calls < max_calls:
            attempt = next_attempt(cached(p.id), p.text, retries)
            if attempt is None:
                break
            call(attempt_key(p.id, attempt), p)
            tally.calls += 1
            tally.retries += attempt > 0
        else:
            return tally
        texts = cached(p.id)
        if first_valid(texts, p.text)[0] is None and len(texts) > retries:
            tally.exhausted += 1
    return tally
