"""Command-line parsing of ``pgrep`` / ``pkill`` uses for ``check_self_matching_pgrep.py`` (D1230).

Pure functions: tokenise the text after the command word, tell options from signal names and
patterns, join backslash-continued lines and find the offending uses in a text.
"""

import re
from collections.abc import Iterator, Sequence

COMMAND = re.compile(r"(?<![\w.-])(pgrep|pkill)(?![\w-])")
BRACKET = re.compile(r"\[[^\]^\\]\]")
EXEMPT_LETTERS = frozenset("xPF")
EXEMPT_LONG = ("--exact", "--parent", "--pidfile")
OK_MARK = "selfmatch-ok:"
STOP = ";&|)\n"
SIGNALS = frozenset(
    [
        "HUP",
        "INT",
        "QUIT",
        "ILL",
        "TRAP",
        "ABRT",
        "BUS",
        "FPE",
        "KILL",
        "USR1",
        "SEGV",
        "USR2",
        "PIPE",
        "ALRM",
        "TERM",
        "STKFLT",
        "CHLD",
        "CONT",
        "STOP",
        "TSTP",
        "TTIN",
        "TTOU",
        "URG",
        "XCPU",
        "XFSZ",
        "VTALRM",
        "PROF",
        "WINCH",
        "IO",
        "PWR",
        "SYS",
    ]
)


def _tokens(rest: str) -> list[str]:
    """Split the text after the command word into argument tokens (quotes honoured).

    It stops at a separator. An unmatched quote ends the command (it closes an outer
    ``ssh 'pkill ...'`` string).

    >>> _tokens(" -f 'a b' c; echo")
    ['-f', 'a b', 'c']
    >>> _tokens(" -f foo'")
    ['-f', 'foo']
    """
    tokens: list[str] = []
    i, n = 0, len(rest)
    while i < n:
        ch = rest[i]
        if ch in STOP:
            break
        if ch in " \t":
            i += 1
            continue
        if ch in "'\"":
            end = rest.find(ch, i + 1)
            if end == -1:
                break
            tokens.append(rest[i + 1 : end])
            i = end + 1
            continue
        j = i
        while j < n and rest[j] not in " \t" + STOP + "'\"":
            j += 1
        tokens.append(rest[i:j].replace("\\", ""))
        if j < n and rest[j] in "'\"" and rest.find(rest[j], j + 1) == -1:
            break  # unmatched closing quote of an outer string
        i = j
    return tokens


def flags_of(tokens: Sequence[str]) -> tuple[set[str], list[str]]:
    """Return the option letters/words used and the remaining (pattern) tokens.

    Signal names (``-HUP``, ``-SIGSTOP``, ``-9``) are skipped; everything after ``--`` is a pattern.

    >>> letters, rest = flags_of(["-9", "-fx", "pat"])
    >>> sorted(letters), rest
    (['f', 'x'], ['pat'])
    >>> flags_of(["-HUP", "-f", "--", "-x"])
    ({'f'}, ['-x'])
    """
    letters: set[str] = set()
    rest: list[str] = []
    after_dashes = False
    for tok in tokens:
        if after_dashes:
            rest.append(tok)
        elif tok == "--":
            after_dashes = True
        elif tok.startswith("--") and len(tok) > 2:
            letters.add(tok.split("=", 1)[0])
        elif re.fullmatch(r"-[A-Za-z][A-Za-z0-9]*", tok):
            body = tok[1:]
            if body.upper().removeprefix("SIG") not in SIGNALS:
                letters.update(body)
        elif not re.fullmatch(r"-\d+", tok):
            rest.append(tok)
    return letters, rest


def offends(tokens: Sequence[str]) -> bool:
    """Return True when the pgrep/pkill arguments use ``-f`` without an accepted safeguard.

    >>> offends(["-f", "worker"]), offends(["-f", "[w]orker"]), offends(["-fx", "worker"])
    (True, False, False)
    >>> offends(["-HUP", "-f", "w"]), offends(["-f", "--", "-x"])
    (True, True)
    >>> offends(["-u", "me", "-P", "1", "-f", "w"])
    False
    """
    letters, rest = flags_of(tokens)
    if "f" not in letters and "--full" not in letters:
        return False
    if letters & EXEMPT_LETTERS or any(word in letters for word in EXEMPT_LONG):
        return False
    return not any(BRACKET.search(tok) for tok in rest)


def logical_lines(text: str) -> Iterator[tuple[int, str]]:
    r"""Yield ``(first line number, text)`` with backslash-continued lines joined.

    >>> list(logical_lines("pgrep \\\n  -f x\nb"))
    [(1, 'pgrep    -f x'), (3, 'b')]
    """
    buf, start = "", 0
    for number, line in enumerate(text.split("\n"), start=1):
        if not buf:
            start = number
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
            continue
        yield start, buf + line
        buf = ""
    if buf:
        yield start, buf


def scan_text(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(line number, source line)`` of every offending pgrep/pkill use in ``text``."""
    for number, line in logical_lines(text):
        if line.lstrip().startswith("#") or OK_MARK in line:
            continue
        flat = re.sub(r'"\s*,\s*"', " ", line)  # exec-form lists: ["pgrep", "-f", "x"]
        for match in COMMAND.finditer(flat):
            if offends(_tokens(flat[match.end() :])):
                yield number, line.strip()
                break
