"""The exact token count of a judge prompt (X3.9, D1010): the catalogue tokenizer, sha256-checked.

The conservative estimate (``estimate_tokens``) over-counts German prose about 2.2x and so cannot
tell a cut prompt from a normal one by comparing it with what Ollama reports. The exact count can.
The ``tokenizer.json`` of the judge (33 MB for gemma3) is never committed: it is fetched once, at
image build or on the executor, by ``scripts/models/fetch_judge_tokenizer.py``, and checked against
the sha256 pin of ``infra/gpu/models.yaml`` before every use. Without the file the exact
comparison is skipped and the run says so (``counts["judge_exact_count_unavailable"]``).
"""

import hashlib
import os
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import httpx
from tokenizers import Tokenizer

from pruefstand.core.errors import ConfigError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.llm import Message
from pruefstand.core.settings import PruefstandSettings
from pruefstand.llm.policy import provider_of
from pruefstand.llm.providers import catalogue_entry

_log = get_logger(__name__)
HF = "https://huggingface.co"
TIMEOUT_S = 120
TEMPLATE_TOKENS = 10
"""Chat-template tokens around one single-turn prompt, calibrated on gemma3:12b (D1010): Ollama
reported 910 / 3 610 / 7 210 / 10 810 prompt tokens for 500 / 2 000 / 4 000 / 6 000 words of 1.8
tokens, an overhead of exactly 10 each time (``<bos>``, two turn markers and their newlines)."""
SEPARATOR = "\n\n"  # the gemma template puts the system message in front of the first user turn
CUT_RATIO = 0.8
"""A report below this share of the exact count (after the cached prefix) is a cut prompt."""
NEAR_WINDOW = 0.9
"""Only a prompt of at least this share of ``num_ctx - num_predict`` can have been cut (measured:
10 810 tokens fit, 14 000 were cut in a window of 11 904)."""


def source_url(source: str) -> str:
    """Map a catalogue source ``hf:<org>/<repo>[@<revision>]/<file>`` to its download URL.

    Raises:
        ConfigError: The source is not of that form.

    Examples:
        >>> source_url("hf:unsloth/gemma-3-12b-it@abc123/tokenizer.json")
        'https://huggingface.co/unsloth/gemma-3-12b-it/resolve/abc123/tokenizer.json'
    """
    prefix, _, rest = source.partition(":")
    parts = rest.split("/")
    if prefix != "hf" or len(parts) < 3:
        msg = f"tokenizer source {source!r} must look like hf:<org>/<repo>[@<rev>]/<file>"
        raise ConfigError(msg)
    repo, _, revision = parts[1].partition("@")
    return f"{HF}/{parts[0]}/{repo}/resolve/{revision or 'main'}/{'/'.join(parts[2:])}"


def tokenizer_file(model_id: str) -> Path:
    """Where the tokenizer of ``model_id`` lives: ``$PRUEFSTAND_JUDGE_TOKENIZER_DIR/<tag>.json``."""
    tag = catalogue_entry(model_id).tag.replace(":", "_").replace("/", "_")
    return PruefstandSettings().judge_tokenizer_dir / f"{tag}.json"


def _pin(model_id: str) -> tuple[str, str]:
    entry = catalogue_entry(model_id)
    if entry.tokenizer_source is None or entry.tokenizer_sha256 is None:
        msg = f"catalogue entry {model_id!r} has no tokenizer pin"
        raise ConfigError(msg)
    return entry.tokenizer_source, entry.tokenizer_sha256


def fetch_tokenizer(model_id: str, out: Path | None = None) -> Path:
    """Download the pinned tokenizer of ``model_id``, verify its sha256 and write it atomically.

    Raises:
        ConfigError: No pin, a bad source, a failed download or a digest mismatch.
    """
    source, sha256 = _pin(model_id)
    target = out or tokenizer_file(model_id)
    url = source_url(source)
    try:
        resp = httpx.get(url, timeout=TIMEOUT_S, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as err:
        msg = f"cannot download {url}: {type(err).__name__}"
        raise ConfigError(msg) from None
    actual = hashlib.sha256(resp.content).hexdigest()
    if actual != sha256:
        msg = f"tokenizer sha256 {actual} differs from the catalogue pin {sha256}"
        raise ConfigError(msg)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    part.write_bytes(resp.content)
    part.replace(target)
    return target


class ExactCounter:
    """Exact prompt-token counts with the judge's own tokenizer."""

    def __init__(self, tokenizer: Tokenizer) -> None:
        self._tokenizer = tokenizer

    def count(self, text: str) -> int:
        """Return the token count of ``text`` (special tokens in the text count as written)."""
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def prompt(self, messages: Sequence[Message]) -> int:
        """Return the tokens of the rendered chat: the joined messages plus the template."""
        return self.count(SEPARATOR.join(m.content for m in messages)) + TEMPLATE_TOKENS

    def fixed_prefix(self, messages: Sequence[Message]) -> int:
        """Return the tokens that every call of this prompt shares, hence may be served from cache.

        That is everything before the first input block: the system message and the lead-in of
        the user message up to its first ``<`` (the nonce-wrapped blocks start there).
        """
        *system, user = messages
        lead = user.content.split("<", 1)[0]
        return self.count(SEPARATOR.join([*(m.content for m in system), lead])) + TEMPLATE_TOKENS


@lru_cache(maxsize=4)
def _load(path: str, sha256: str) -> ExactCounter:
    raw = Path(path).read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != sha256:
        msg = f"{path}: sha256 {actual} differs from the catalogue pin {sha256}"
        raise ConfigError(msg)
    return ExactCounter(Tokenizer.from_str(raw.decode("utf-8")))


def load_counter(model_id: str) -> ExactCounter | None:
    """Return the exact counter of an Ollama judge, or None when its tokenizer file is absent.

    Raises:
        ConfigError: The file exists and is pinned but differs from the pin (a wrong file is an
            error, never a silent skip).
    """
    if provider_of(model_id) != "ollama":
        return None
    sha256 = catalogue_entry(model_id).tokenizer_sha256
    path = Path(os.fspath(tokenizer_file(model_id)))
    if sha256 is None or not path.is_file():  # no pin or no file: the exact count is skipped
        return None
    return _load(str(path), sha256)


def is_cut(reported: int, exact: int, prefix: int, window: int) -> bool:
    """Whether a reported prompt count shows a cut prompt (sign (c) of ``Judge._check_not_cut``).

    Only a prompt that nearly fills the window (``exact >= NEAR_WINDOW`` of it) can have been cut;
    for it, the lowest honest report is the exact count minus the fixed prefix a prompt cache may
    serve (D343), and a report below ``CUT_RATIO`` of that is read as cut. A short prompt that
    Ollama reports as tiny (a full cache hit on a repeat) is therefore never flagged.

    Examples:
        >>> is_cut(6147, 14_000, 1_500, 11_904), is_cut(300, 3_000, 1_500, 11_904)
        (True, False)
        >>> is_cut(11_000, 11_500, 1_500, 11_904), is_cut(7_000, 11_500, 1_500, 11_904)
        (False, True)
    """
    if exact < NEAR_WINDOW * window:
        return False
    return reported < CUT_RATIO * max(exact - prefix, 0)
