"""Number formats (ui-spec §10.2) and Markdown neutralisation for the PR comment.

Everything the target or a branch name controls (case ids, slice values, git refs, evidence)
reaches the comment only through ``md_escape`` / ``md_code`` / ``safe_url``. All of them are
linear in the input size (single passes, bounded character classes) and cap their output.
"""

import math
import re
from urllib.parse import urlsplit

from pruefstand.core.models.run import CostSummary, RunManifest

DASH = "–"
ZWSP = "\u200b"
MAX_TEXT = 200
MAX_URL = 2000
_SHA = re.compile(r"[0-9a-fA-F]{7,64}")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]")
_SPACE = re.compile(r"[ \t\r\n]+")
_PUNCT = re.compile(r"([\\*~\[\]()!|$`])")
_UNDERSCORE = re.compile(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])")
_HTML = {"<": "&lt;", ">": "&gt;", "&": "&amp;"}
_HTML_RE = re.compile(r"[<>&]")
_AUTOLINK = re.compile(r"(?i)(://|www\.)")
_REF = re.compile(r"#(?=\d)")
_URL_BAD = re.compile(r"[\s<>\"\\\x00-\x1f\x7f]")


def fmt_num(value: float | None) -> str:
    """Return ``value`` with two decimals, or an en dash for ``None`` / non-finite."""
    if value is None or not math.isfinite(value):
        return DASH
    return f"{value:.2f}"


def fmt_signed(value: float | None) -> str:
    """Return ``value`` with an explicit sign and a Unicode minus (``+0.01``, ``−0.07``).

    A value that rounds to zero is shown as ``+0.00``.
    """
    if value is None or not math.isfinite(value):
        return DASH
    text = f"{value:.2f}"
    if text.lstrip("-") == "0.00":
        return "+0.00"
    return text.replace("-", "−") if value < 0 else f"+{text}"


def fmt_delta(mean: float | None, low: float | None, high: float | None) -> str:
    """Return ``Δ (low, high)``, e.g. ``−0.07 (−0.10, −0.04)``; a dash without a result."""
    if mean is None or low is None or high is None:
        return DASH
    return f"{fmt_signed(mean)} ({fmt_signed(low)}, {fmt_signed(high)})"


def fmt_mde(value: float | None) -> str:
    """Return a δ / MDE / max value: two decimals, no sign."""
    return fmt_num(value)


def fmt_duration(seconds: float) -> str:
    """Return ``Xm Ys`` (``18m 12s``); negative or non-finite input counts as zero."""
    total = int(seconds) if math.isfinite(seconds) and seconds > 0 else 0
    return f"{total // 60}m {total % 60:02d}s"


def fmt_usd(usd: float) -> str:
    """Return ``0.18 USD``; an amount that rounds to zero reads ``0 USD`` (SPEC §7.6)."""
    text = f"{usd:.2f}" if math.isfinite(usd) else "0.00"
    return "0 USD" if text in {"0.00", "-0.00"} else f"{text} USD"


def fmt_tokens(cost: CostSummary) -> str:
    """Return the token sum (prompt + completion) as ``4.1 M``, ``812 k`` or ``< 1 k``."""
    total = cost.prompt_tokens + cost.completion_tokens
    if total < 1000:
        return "< 1 k"
    if total >= 999_500:
        return f"{total / 1_000_000:.1f} M"
    return f"{round(total / 1000)} k"


def fmt_gpu(seconds: float) -> str:
    """Return ``~2,100 GPU-s`` (tier 2 only; the caller checks the stack)."""
    return f"~{round(seconds):,} GPU-s" if math.isfinite(seconds) and seconds > 0 else "~0 GPU-s"


def _clean(text: str, limit: int) -> str:
    """Drop control and bidi characters, fold white space to single spaces, cap the length."""
    folded = _SPACE.sub(" ", _CONTROL.sub("", text[: limit * 4])).strip()
    return folded if len(folded) <= limit else folded[:limit].rstrip() + "…"


def md_escape(text: str, *, limit: int = MAX_TEXT) -> str:
    r"""Neutralise ``text`` for one Markdown table cell or line.

    Escapes ``| ` * ~ [ ] ( ) ! $ \\`` and ``_`` outside words, HTML (``< > &``), breaks ``@``
    mentions, ``#123`` issue references, ``://`` and ``www.`` autolinks with a zero-width space,
    folds line breaks and removes control / bidi characters. At most ``limit`` characters of
    ``text`` are kept (plus ``…``).

    Args:
        text: Untrusted text (case id, slice value, branch name, evidence).
        limit: Maximum characters of ``text`` kept before escaping.

    Returns:
        Text that renders as the literal characters and triggers nothing.

    Example:
        >>> md_escape("a|b @x <i>")
        'a\\|b @\u200bx &lt;i&gt;'
    """
    out = _UNDERSCORE.sub(r"\\_", _PUNCT.sub(r"\\\1", _clean(text, limit)))
    out = _HTML_RE.sub(lambda m: _HTML[m.group()], out)
    out = out.replace("@", "@" + ZWSP)
    out = _AUTOLINK.sub(lambda m: m.group()[:1] + ZWSP + m.group()[1:], out)
    return _REF.sub("#" + ZWSP, out)


def md_code(text: str | None, *, limit: int = MAX_TEXT) -> str:
    """Return ``text`` as a one-line code span that cannot be closed from inside.

    Backticks are removed, ``|`` is escaped for table cells. Empty input yields an en dash.
    """
    if text is None:
        return DASH
    body = _clean(text.replace("`", "'"), limit).replace("|", "\\|")
    body = (
        body.replace("![", "!" + ZWSP + "[")
        .replace("<", "\u2039")
        .replace(">", "\u203a")
        .replace("](", "]" + ZWSP + "(")
    )
    body = _AUTOLINK.sub(lambda m: m.group()[:1] + ZWSP + m.group()[1:], body)
    body = _REF.sub("#" + ZWSP, body.replace("@", "@" + ZWSP))
    return f"`{body}`" if body else DASH


def safe_url(url: str | None) -> str | None:
    """Return ``url`` if it is a plain ``http(s)`` URL safe inside ``<...>``, else ``None``."""
    if not url or len(url) > MAX_URL or _URL_BAD.search(url):
        return None
    parts = urlsplit(url)
    return url if parts.scheme in {"http", "https"} and parts.netloc else None


def ref_label(manifest: RunManifest) -> str:
    """Return the ref label of ui-spec §2.2: ``pr-<n>``, ``git_ref`` or ``–``, plus ``@<sha7>``."""
    if manifest.pr_number is not None:
        label = f"pr-{manifest.pr_number}"
    elif manifest.git_ref:
        label = md_escape(manifest.git_ref, limit=80)
    else:
        label = ""
    sha = manifest.git_sha
    short = f"@{sha[:7]}" if sha and _SHA.fullmatch(sha) else ""
    return f"{label}{short}" if label or short else DASH
