"""Flag ``pgrep -f`` / ``pkill -f`` that can match more than the intended process (D1230).

Scans shell scripts, Makefiles / ``mk/*.mk`` and the ``run:`` blocks of workflows (text inside
quotes, such as ``ssh host 'pkill -f x'``, and heredoc bodies included). A full-command-line match
also hits the shell that carries the pattern in its own command line and every other session whose
arguments contain it (a ``pkill -f`` once killed another session's polling loop). Accepted: the
bracket trick (``pgrep -f '[x]yz'``), ``-x`` / ``--exact``, ``-P`` / ``--parent``, ``-F`` /
``--pidfile`` (a PID file), a PID kept by the caller (no pgrep at all), or a
``# selfmatch-ok: <reason>`` comment on the line.

Usage: ``python scripts/check_self_matching_pgrep.py [ROOT]`` (default: the repository root).
Prints one finding per line and exits 1, or prints ``ok: N files checked`` and exits 0.
"""

import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

import yaml

COMMAND = re.compile(r"(?<![\w.-])(pgrep|pkill)(?![\w-])")
BRACKET = re.compile(r"\[[^\]^\\]\]")
EXEMPT_LETTERS = frozenset("xPF")
EXEMPT_LONG = ("--exact", "--parent", "--pidfile")
OK_MARK = "selfmatch-ok:"
SKIP_DIRS = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache"}
)
STOP = ";&|)\n"


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

    >>> flags_of(["-9", "-fx", "pat"])
    ({'f', 'x'}, ['pat'])
    """
    letters: set[str] = set()
    rest: list[str] = []
    for tok in tokens:
        if tok.startswith("--") and len(tok) > 2:
            letters.add(tok.split("=", 1)[0])
        elif re.fullmatch(r"-[A-Za-z]+", tok):
            letters.update(tok[1:])
        elif not re.fullmatch(r"-\d+", tok):
            rest.append(tok)
    return letters, rest


def offends(tokens: Sequence[str]) -> bool:
    """Return True when the pgrep/pkill arguments use ``-f`` without an accepted safeguard.

    >>> offends(["-f", "worker"]), offends(["-f", "[w]orker"]), offends(["-fx", "worker"])
    (True, False, False)
    >>> offends(["-x", "worker"]), offends(["-u", "me", "-P", "1", "-f", "w"])
    (False, False)
    """
    letters, rest = flags_of(tokens)
    if "f" not in letters and "--full" not in letters:
        return False
    if letters & EXEMPT_LETTERS or any(word in letters for word in EXEMPT_LONG):
        return False
    return not any(BRACKET.search(tok) for tok in rest)


def scan_text(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(line number, source line)`` of every offending pgrep/pkill use in ``text``."""
    for number, line in enumerate(text.split("\n"), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#") or OK_MARK in line:
            continue
        for match in COMMAND.finditer(line):
            if offends(_tokens(line[match.end() :])):
                yield number, line.strip()
                break


def workflow_run_blocks(text: str) -> list[tuple[int, str]]:
    """Return ``(first line, script)`` of every ``run:`` value found in a workflow YAML document."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return [(1, text)]
    blocks: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "run" and isinstance(value, str):
                    blocks.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    lines = text.split("\n")
    out: list[tuple[int, str]] = []
    for block in blocks:
        first = block.strip().split("\n")[0]
        at = next((i for i, ln in enumerate(lines, start=1) if first and first in ln), 1)
        out.append((at, block))
    return out


def _is_shell(path: Path) -> bool:
    if path.suffix in {".sh", ".bash"}:
        return True
    if path.suffix or path.name == "Makefile":
        return False
    try:
        with path.open("rb") as fh:
            first = fh.readline(80)
    except OSError:
        return False
    return first.startswith(b"#!") and b"sh" in first


def candidate_files(root: Path) -> Iterator[Path]:
    """Yield the files to scan: tracked files of a git checkout, else a directory walk."""
    res = subprocess.run(  # noqa: S603  # fixed argv
        ["git", "-C", str(root), "ls-files", "-z"],  # noqa: S607  # git from PATH
        capture_output=True,
        check=False,
        timeout=60,
    )
    if res.returncode == 0 and res.stdout:
        names = [Path(p.decode("utf-8", "replace")) for p in res.stdout.split(b"\0") if p]
        paths = [root / n for n in names]
    else:
        paths = [
            p
            for p in root.rglob("*")
            if p.is_file() and SKIP_DIRS.isdisjoint(p.relative_to(root).parts)
        ]
    for path in sorted(paths):
        if path.is_file() and not path.is_symlink():
            yield path


def file_findings(path: Path, root: Path) -> list[str]:
    """Return the findings of one file (``rel:line: message``)."""
    rel = path.relative_to(root).as_posix()
    kind = ""
    if rel.startswith(".github/workflows/") and path.suffix in {".yml", ".yaml"}:
        kind = "workflow"
    elif path.suffix == ".mk" or path.name == "Makefile" or _is_shell(path):
        kind = "shell"
    if not kind:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    hits: list[tuple[int, str]] = []
    if kind == "workflow":
        for first, block in workflow_run_blocks(text):
            hits.extend((first + n - 1, src) for n, src in scan_text(block))
    else:
        hits.extend(scan_text(text))
    msg = (
        "pgrep/pkill -f can match its own or another command line ('[x]yz', -x, -P, -F, PID file): "
    )
    return [f"{rel}:{n}: {msg}{src}" for n, src in hits]


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry: scan ``ROOT`` (default: the repository root) and report."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path(__file__).resolve().parents[1]
    findings: list[str] = []
    count = 0
    for path in candidate_files(root):
        count += 1
        findings.extend(file_findings(path, root))
    for line in findings:
        sys.stdout.write(line + "\n")
    if findings:
        return 1
    sys.stdout.write(f"ok: {count} files checked\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
