"""Test kit for the T0.7 VM script tests (stubs, restricted PATH); imported by ``infra/vm/tests``.

The scripts under ``infra/vm`` are run with a *restricted* ``PATH``: only a short allow-list of
harmless real tools plus per-test stubs. Real ``sudo``, ``docker``, ``iptables``, ``systemctl``,
``ssh``, ``curl`` or ``gh`` are never reachable, so a test can never touch the machine it runs on.
"""

import shlex
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


def bash() -> str:
    """Absolute path of the real bash used to start the scripts."""
    return shutil.which("bash") or "bash"


VM_DIR = Path(__file__).resolve().parent
REPO = VM_DIR.parents[1]

# Real tools a script may use under test (nothing that can change the system or reach a network).
SAFE_TOOLS = [
    "bash",
    "sh",
    "env",
    "grep",
    "egrep",
    "awk",
    "sed",
    "cut",
    "sort",
    "tr",
    "cat",
    "head",
    "tail",
    "mkdir",
    "chmod",
    "touch",
    "rm",
    "mv",
    "cp",
    "cmp",
    "install",
    "dirname",
    "basename",
    "date",
    "id",
    "uname",
    "wc",
    "mktemp",
    "ls",
    "tee",
    "readlink",
    "realpath",
    "ssh-keygen",
    "stat",
    "flock",
    "python3",
    "sleep",
    "true",
    "false",
    "uniq",
    "xargs",
    "comm",
    "find",
    "hostname",
    "tac",
    "printf",
    "test",
    "nproc",
    "diff",
    "chown",
    "df",
    "timeout",
    "mountpoint",
]

Rule = tuple[str, str, int] | tuple[str, str, int, str]


@dataclass
class Stubs:
    """A directory of stub executables that log every call to ``log``."""

    root: Path

    def __post_init__(self) -> None:
        self.bin = self.root / "bin"
        self.bin.mkdir(parents=True, exist_ok=True)
        self.log = self.root / "stub.log"
        self.log.touch()
        for tool in SAFE_TOOLS:
            real = shutil.which(tool)
            if real and not (self.bin / tool).exists():
                (self.bin / tool).symlink_to(real)

    def add(self, name: str, rules: Sequence[Rule] = (), default_rc: int = 99) -> None:
        """Write a stub ``name``; the first rule whose glob matches ``"$*"`` gives output and rc."""
        lines = [
            "#!/usr/bin/env bash",
            f'echo {shlex.quote(name)}" $*" >> {shlex.quote(str(self.log))}',
        ]
        lines.append('args="$*"')
        lines.append('case "$args" in')
        for rule in rules:
            pattern, out, rc = rule[0], rule[1], rule[2]
            err = rule[3] if len(rule) == 4 else ""
            glob = "*".join(shlex.quote(part) if part else "" for part in pattern.split("*"))
            lines.append(f"  {glob})")
            if "{n}" in out:
                counter = shlex.quote(str(self.root / f"count-{name}"))
                lines.append(
                    f"    n=$(( $(cat {counter} 2>/dev/null || echo 0) + 1 )); echo $n > {counter}"
                )
                lines.append(
                    f"    printf '%s\\n' {shlex.quote(out.replace('{n}', '@N@'))}"
                    f' | sed "s/@N@/$n/"'
                )
            elif out:
                lines.append(f"    printf '%s\\n' {shlex.quote(out)}")
            if err:
                lines.append(f"    printf '%s\\n' {shlex.quote(err)} >&2")
            lines.append(f"    exit {rc};;")
        lines.append("esac")
        lines.append(f'echo "UNEXPECTED stub call: {name} $*" >&2')
        lines.append(f"exit {default_rc}")
        target = self.bin / name
        target.unlink(missing_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        target.chmod(0o755)

    def add_sudo(self) -> None:
        """A ``sudo`` that logs, drops ``-n``/``-u USER`` and runs the rest from the stub PATH."""
        target = self.bin / "sudo"
        target.unlink(missing_ok=True)
        target.write_text(
            "#!/usr/bin/env bash\n"
            f'echo "sudo $*" >> {shlex.quote(str(self.log))}\n'
            'while [ $# -gt 0 ]; do case "$1" in -n) shift;; -u) shift 2;; *) break;; esac; done\n'
            'exec "$@"\n',
            encoding="utf-8",
        )
        target.chmod(0o755)

    def link(self, name: str, target: Path) -> None:
        """Expose a real file of the repo under ``name`` (e.g. the ``pruefstand-lock`` wrapper)."""
        (self.bin / name).unlink(missing_ok=True)
        (self.bin / name).symlink_to(target)

    def calls(self, name: str | None = None) -> list[str]:
        """Return the logged stub calls, optionally only those of ``name``."""
        rows = self.log.read_text(encoding="utf-8").splitlines()
        return [r for r in rows if name is None or r.split(" ", 1)[0] == name]


@dataclass
class Result:
    """Outcome of one script run."""

    rc: int
    out: str
    err: str


Runner = Callable[..., Result]
