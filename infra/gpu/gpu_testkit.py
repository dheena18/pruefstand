"""Test kit for the T3.1a script tests (cluster scripts and VM scripts); imported by both test dirs.

Scripts run with a *restricted* ``PATH``: a short allow-list of harmless real tools plus per-test stubs
(``vm_testkit.Stubs``). Real ``ssh``, ``curl``, ``sudo``, ``nvidia-smi`` or ``ollama`` are never
reachable, so a test cannot touch the machine it runs on or any cluster. Stubs fake the *shell
environment* (exit codes, canned HTTP bodies), never a model (ADR-0008).
"""

import getpass
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from vm_testkit import Result, Rule, Stubs

REPO = Path(__file__).resolve().parents[2]
CLUSTER_DIR = REPO / "infra" / "cluster"
GPU_DIR = REPO / "infra" / "gpu"
EXTRA_TOOLS = ("sha256sum", "tr", "wc", "sed", "awk", "sort", "grep", "cut", "head", "tail", "ls")
GEN_DIGEST = "8f5fb6b71ea00052cbe8545738c55ce61112c4e571cb60ca4dad00b131766039"


def link_tools(stubs: Stubs, *names: str) -> None:
    """Expose real harmless tools under the restricted PATH."""
    for name in names or EXTRA_TOOLS:
        real = shutil.which(name)
        if real and not (stubs.bin / name).exists():
            (stubs.bin / name).symlink_to(real)


def python_stub(stubs: Stubs) -> None:
    """``python3`` in the restricted PATH runs the interpreter of the test environment (has PyYAML)."""
    target = stubs.bin / "python3"
    target.unlink(missing_ok=True)
    target.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n', encoding="utf-8")
    target.chmod(0o755)


def run_script(
    script: Path,
    *args: object,
    stubs: Stubs,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    cwd: Path | None = None,
    timeout: int = 60,
) -> Result:
    """Run ``bash <script> args`` with the restricted PATH; ``env`` adds or overrides variables."""
    full = {"PATH": str(stubs.bin), "HOME": str(stubs.root / "home"), "LC_ALL": "C.UTF-8"}
    full.update(env or {})
    proc = subprocess.run(  # noqa: S603
        [shutil.which("bash") or "bash", str(script), *map(str, args)],
        env=full,
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd or stubs.root,
        timeout=timeout,
        check=False,
    )
    return Result(proc.returncode, proc.stdout, proc.stderr)


def fake_ssh(stubs: Stubs, remote_root: Path) -> None:
    """A local ``ssh``: runs the remote command in bash with ``/data/dheena`` mapped to ``remote_root``.

    Options (``-o x``, ``-q``, ``--``) and the host are dropped; stdin is passed through. Every call
    is logged as ``ssh <args>``.
    """
    script = f"""#!/usr/bin/env bash
echo "ssh $*" >> {shlex.quote(str(stubs.log))}
while [ $# -gt 0 ]; do
  case "$1" in -o) shift 2;; -q|-T|-n) shift;; --) shift; break;; -*) shift;; *) break;; esac
done
shift  # the host
cmd="$*"
cmd="${{cmd//\\/data\\/dheena/{remote_root}}}"
exec bash -c "$cmd"
"""
    target = stubs.bin / "ssh"
    target.unlink(missing_ok=True)
    target.write_text(script, encoding="utf-8")
    target.chmod(0o755)


def add_proc(
    proc: Path, pid: int, cmdline: Sequence[str], environ: dict[str, str] | None = None
) -> Path:
    """Create ``proc/<pid>/{cmdline,environ}`` (NUL separated, like Linux)."""
    pdir = proc / str(pid)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "cmdline").write_bytes(b"\0".join(c.encode() for c in cmdline) + b"\0")
    (pdir / "environ").write_bytes(
        b"".join(f"{k}={v}".encode() + b"\0" for k, v in (environ or {}).items())
    )
    return pdir


CLUSTER_ENV_KEYS = {
    "CUDA_VISIBLE_DEVICES": "0,1",
    "OLLAMA_HOST": "127.0.0.1:11434",
    "OLLAMA_NUM_PARALLEL": "4",
    "OLLAMA_MAX_LOADED_MODELS": "3",
    "OLLAMA_KEEP_ALIVE": "24h",
    "OLLAMA_CONTEXT_LENGTH": "8192",
    "OLLAMA_FLASH_ATTENTION": "1",
    "OLLAMA_KV_CACHE_TYPE": "q8_0",
    "OLLAMA_NOPRUNE": "1",
}


@dataclass
class ClusterWorld:
    """A fake cluster account: a bin dir with copies of the scripts, ``cluster.env``, HOME, /proc."""

    root: Path
    stubs: Stubs
    bin_dir: Path = field(init=False)
    home: Path = field(init=False)
    models: Path = field(init=False)
    proc: Path = field(init=False)
    log: Path = field(init=False)
    marker: Path = field(init=False)

    def __post_init__(self) -> None:
        self.bin_dir = self.root / "pruefstand-bin"
        self.home = self.stubs.root / "home"
        self.models = self.root / "Models"
        self.proc = self.root / "proc"
        self.log = self.root / "ollama.log"
        self.marker = self.root / "start-marker"
        for d in (self.bin_dir, self.home, self.models, self.proc):
            d.mkdir(parents=True, exist_ok=True)
        for script in CLUSTER_DIR.glob("*.sh"):
            shutil.copy(script, self.bin_dir / script.name)
        self.write_env()
        start = self.home / "start-ollama.sh"
        start.write_text(f"#!/bin/sh\necho started >> {shlex.quote(str(self.marker))}\n")
        start.chmod(0o755)
        link_tools(self.stubs)

    def write_env(self, overrides: dict[str, str] | None = None) -> None:
        """Write ``cluster.env`` (template values, test paths) and ``SHA256SUMS`` of the bin dir."""
        values = {
            **CLUSTER_ENV_KEYS,
            "OLLAMA_MODELS": str(self.models),
            "OLLAMA_START_SCRIPT": "$HOME/start-ollama.sh",
            "OLLAMA_LOG": str(self.log),
            "MODELS_MIN_FREE_GB": "2",
            "GENERATOR_TAG": "qwen3.8:27b-q8_0",
            **(overrides or {}),
        }
        text = "".join(f"{k}={v}\n" for k, v in values.items())
        (self.bin_dir / "cluster.env").write_text(text, encoding="utf-8")
        sums = subprocess.run(  # noqa: S603
            [shutil.which("sha256sum") or "sha256sum", *sorted(p.name for p in self.bin_dir.iterdir() if p.name != "SHA256SUMS")],
            cwd=self.bin_dir, capture_output=True, text=True, check=True,
        )  # fmt: skip
        (self.bin_dir / "SHA256SUMS").write_text(sums.stdout, encoding="utf-8")

    def env(self, **extra: str) -> dict[str, str]:
        """Environment for a script run: the fake proc root and a private HOME."""
        return {"PRUEFSTAND_PROC_ROOT": str(self.proc), "HOME": str(self.home), **extra}

    def script(self, name: str, *args: object, **extra: str) -> Result:
        """Run ``<bin dir>/<name>`` (its own copy, so it sources the test ``cluster.env``)."""
        return run_script(self.bin_dir / name, *args, stubs=self.stubs, env=self.env(**extra))

    def add_serve(self, pid: int, environ: dict[str, str] | None = None) -> None:
        """A running ``ollama serve`` whose environment matches ``cluster.env`` unless overridden."""
        env = {**CLUSTER_ENV_KEYS, "OLLAMA_MODELS": str(self.models), **(environ or {})}
        pdir = add_proc(self.proc, pid, ["/usr/local/bin/ollama", "serve"], env)
        fake_bin = self.root / "ollama-bin"
        fake_bin.write_text(f'#!/bin/sh\necho "ollama $*" >> {shlex.quote(str(self.stubs.log))}\n')
        fake_bin.chmod(0o755)
        (pdir / "exe").symlink_to(fake_bin)

    def stub_server(self, pids: Sequence[int] = (4242,), *, listening: bool = True) -> None:
        """Stub ``pgrep`` and ``ss`` for the given server pids (the first one listens)."""
        out = "\n".join(map(str, pids))
        self.stubs.add("pgrep", [("-u * -x ollama", out, 0 if pids else 1)])
        listener = (
            f'LISTEN 0 4096 127.0.0.1:11434 0.0.0.0:* users:(("ollama",pid={pids[0]},fd=3))'
            if pids and listening
            else ""
        )
        self.stubs.add("ss", [("*", listener, 0)])


def rules(*items: Rule) -> list[Rule]:
    """Typed helper for a stub rule list."""
    return list(items)
