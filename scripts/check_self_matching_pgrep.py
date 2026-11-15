"""Flag ``pgrep -f`` / ``pkill -f`` that can match more than the intended process (D1230).

Scans shell scripts (``.sh``, ``.bash``, ``.zsh``, extensionless with an sh shebang), Makefiles
and ``mk/*.mk``, systemd ``.service`` files, Dockerfiles (``HEALTHCHECK``, ``RUN``), the ``run:``
blocks of workflows and composite actions, and the command strings of Python ``subprocess`` /
``os.system`` calls. Text inside quotes (``ssh host 'pkill -f x'``), heredoc bodies and
backslash-continued lines are covered. A full-command-line match also hits the shell that carries
the pattern in its own command line and every other session whose arguments contain it (a
``pkill -f`` once killed another session's polling loop). Accepted: the bracket trick
(``pgrep -f '[x]yz'``), ``-x`` / ``--exact``, ``-P`` / ``--parent``, ``-F`` / ``--pidfile`` (a PID
file), a PID kept by the caller (no pgrep at all), or a ``# selfmatch-ok: <reason>`` comment on the
line. Signal names (``-HUP``, ``-STOP``) are not options.

Usage: ``python scripts/check_self_matching_pgrep.py [ROOT]`` (default: the repository root).
Prints one finding per line and exits 1, or prints ``ok: N files checked`` and exits 0.
"""

import ast
import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

import yaml
from pgrep_tokens import OK_MARK, scan_text

SKIP_DIRS = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache"}
)
SHELL_SUFFIXES = frozenset({".sh", ".bash", ".zsh", ".mk", ".service"})
PY_CALLS = frozenset(
    {"system", "popen", "run", "call", "check_call", "check_output", "Popen", "getoutput"}
    | {"getstatusoutput", "create_subprocess_shell", "create_subprocess_exec"}
)
MESSAGE = (
    "pgrep/pkill -f can match its own or another command line ('[x]yz', -x, -P, -F, PID file): "
)


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


def _command_text(node: ast.expr) -> str:
    """Render a call argument (string, f-string or list of strings) as one command line."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            p.value if isinstance(p, ast.Constant) and isinstance(p.value, str) else "X"
            for p in node.values
        )
    if isinstance(node, ast.List | ast.Tuple):
        parts = [
            _command_text(e) if isinstance(e, ast.Constant | ast.JoinedStr) else "X"
            for e in node.elts
        ]
        return " ".join(parts)
    return ""


def scan_python(text: str) -> Iterator[tuple[int, str]]:
    """Yield offending pgrep/pkill command strings passed to subprocess / os.system style calls."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return
    lines = text.split("\n")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in PY_CALLS:
            continue
        end = node.end_lineno or node.lineno
        if any(OK_MARK in ln for ln in lines[node.lineno - 1 : end]):
            continue
        command = _command_text(node.args[0])
        if any(True for _ in scan_text(command)):
            yield node.lineno, lines[node.lineno - 1].strip()


def _is_shell(path: Path) -> bool:
    if path.suffix in SHELL_SUFFIXES or path.name == "Makefile":
        return True
    if (
        path.name == "Dockerfile"
        or path.name.startswith("Dockerfile.")
        or path.suffix == ".dockerfile"
    ):
        return True
    if path.suffix:
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


def _kind(path: Path, rel: str) -> str:
    in_yaml = path.suffix in {".yml", ".yaml"}
    if in_yaml and (rel.startswith(".github/workflows/") or rel.startswith(".github/actions/")):
        return "workflow"
    if path.suffix == ".py":
        return "python"
    return "shell" if _is_shell(path) else ""


def file_findings(path: Path, root: Path) -> list[str]:
    """Return the findings of one file (``rel:line: message``)."""
    rel = path.relative_to(root).as_posix()
    kind = _kind(path, rel)
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
    elif kind == "python":
        hits.extend(scan_python(text))
    else:
        hits.extend(scan_text(text))
    return [f"{rel}:{n}: {MESSAGE}{src}" for n, src in hits]


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
