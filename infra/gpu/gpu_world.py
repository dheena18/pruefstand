"""A healthy fake VM + cluster for the VM-script tests: catalogue rows, ``/api/*`` bodies, stubs.

``GpuWorld`` writes the bodies that ``curl`` stubs answer and the CSV that ``ssh`` stubs print, so
the VM scripts run end to end without a cluster, a GPU or a model (ADR-0008: shell only).
"""

import getpass
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from gpu_testkit import GPU_DIR, link_tools, python_stub, run_script
from vm_testkit import Result, Stubs

CATALOGUE: dict[str, Any] = yaml.safe_load((GPU_DIR / "models.yaml").read_text(encoding="utf-8"))
ENTRIES: dict[str, dict[str, Any]] = {m["tag"]: m for m in CATALOGUE["models"]}
DAY_TAGS = ("qwen3.8:27b-q8_0", "bge-m3", "gemma3:12b")
GIB = 1024**3
DF_HEAD = "Filesystem 1024-blocks Used Available Capacity Mounted on\n"


def reported(tag: str) -> str:
    """The name Ollama reports for a catalogue tag (no ``:`` in the tag means ``<tag>:latest``)."""
    return tag if ":" in tag else f"{tag}:latest"


def ps_model(tag: str, *, digest: str | None = None, vram_ratio: float = 1.0) -> dict[str, Any]:
    """One ``/api/ps`` model row (Ollama 0.32 shape and names) for a catalogue tag."""
    size = ENTRIES[tag]["disk_bytes"] + 4 * GIB
    return {
        "name": reported(tag), "model": reported(tag), "size": size,
        "digest": digest or ENTRIES[tag]["digest"],
        "details": {"family": ENTRIES[tag]["family"]}, "expires_at": "2026-11-03T10:00:00Z",
        "size_vram": int(size * vram_ratio), "context_length": ENTRIES[tag]["options"]["num_ctx"],
    }  # fmt: skip


def status_csv(
    *,
    gpu_used: tuple[int, int] = (36000, 14000),
    free_kb: int = 14_000_000,
    spread: str | None = None,
    sums: str = "0" * 64,
    extra: Sequence[str] = (),
) -> str:
    """The CSV a healthy ``status.sh`` prints (generator + bge-m3 on gpu 0, the judge on gpu 1)."""
    disk_state = "OK" if free_kb >= 2 * 1024 * 1024 else "WARN"
    rows = [
        "check,status,detail",
        "server,OK,pid=4242",
        "start-script,OK,the start script of record exists",
        "listener,OK,127.0.0.1 pid=4242",
        "env,OK,matches cluster.env",
        f"disk-models,{disk_state},free_kb={free_kb} min_free_gb=2",
        "api-tags,OK,models=3",
        f"gpu:0,INFO,uuid=GPU-aaa used_mib={gpu_used[0]} total_mib=46068",
        f"gpu:1,INFO,uuid=GPU-bbb used_mib={gpu_used[1]} total_mib=46068",
        f"placement:{DAY_TAGS[0]},{'WARN' if spread else 'OK'},gpu={spread or '0'}",
        f"placement:{reported(DAY_TAGS[1])},OK,gpu=0",
        f"placement:{DAY_TAGS[2]},OK,gpu=1",
        "bin-integrity,OK,sha256sum -c passed",
        f"bin-sums,INFO,sha256={sums}",
        *extra,
    ]
    return "\n".join(rows)


@dataclass
class GpuWorld:
    """A healthy fake VM + cluster for the VM scripts: lock dir, data root, curl/ssh/df stubs."""

    root: Path
    stubs: Stubs

    def __post_init__(self) -> None:
        self.lock_dir = self.root / "lock"
        self.data_root = self.root / "data"
        for d in (self.lock_dir, self.data_root):
            d.mkdir(parents=True, exist_ok=True)
        (self.lock_dir / "gpu.lock").touch()
        self.tags_file = self.root / "tags.json"
        self.ps_file = self.root / "ps.json"
        self.counter = self.root / "count-tags"
        link_tools(self.stubs)
        python_stub(self.stubs)
        self.set_tags(list(DAY_TAGS))
        self.set_ps([ps_model(t) for t in DAY_TAGS])
        self.curl()
        self.ssh(status_csv(sums=self.expected_sums()))
        df_out = DF_HEAD + "/dev/vda 500000000 50000000 400000000 12% /mnt"
        self.stubs.add("df", [("*", df_out, 0)])

    def expected_sums(self) -> str:
        """sha256 of the SHA256SUMS text that ``deploy-cluster-bin.sh --print-sums`` prints."""
        script = str(GPU_DIR / "deploy-cluster-bin.sh")
        proc = subprocess.run(  # noqa: S603
            [shutil.which("bash") or "bash", script, "--print-sums"],
            capture_output=True,
            env={"PATH": str(self.stubs.bin), "HOME": str(self.root)},
            check=False,
        )  # fmt: skip
        return hashlib.sha256(proc.stdout).hexdigest()

    def set_tags(self, tags: Sequence[str], digests: dict[str, str] | None = None) -> None:
        """Body of ``GET /api/tags``."""
        rows = [
            {
                "name": reported(t), "model": reported(t), "size": ENTRIES[t]["disk_bytes"],
                "digest": (digests or {}).get(t, ENTRIES[t]["digest"]),
            }
            for t in tags
        ]  # fmt: skip
        self.tags_file.write_text(json.dumps({"models": rows}), encoding="utf-8")

    def set_ps(self, models: Sequence[dict[str, Any]]) -> None:
        """Body of ``GET /api/ps``."""
        self.ps_file.write_text(json.dumps({"models": list(models)}), encoding="utf-8")

    def curl(self, *, tags_fail_first: int = 0, generate_rc: int = 0) -> None:
        """A stateful ``curl``: ``/api/tags`` fails ``tags_fail_first`` times (rc 7), then works."""
        self.counter.unlink(missing_ok=True)
        script = f"""#!/usr/bin/env bash
echo "curl $*" >> {shlex.quote(str(self.stubs.log))}
case "$*" in
  *api/tags*)
    n=$(( $(cat {shlex.quote(str(self.counter))} 2>/dev/null || echo 0) + 1 ))
    echo $n > {shlex.quote(str(self.counter))}
    [ "$n" -le {tags_fail_first} ] && exit 7
    cat {shlex.quote(str(self.tags_file))};;
  *api/ps*) cat {shlex.quote(str(self.ps_file))};;
  *api/generate*) [ {generate_rc} -ne 0 ] && exit {generate_rc}; echo '{{"done":true}}';;
  *) echo "UNEXPECTED curl $*" >&2; exit 99;;
esac
"""
        target = self.stubs.bin / "curl"
        target.unlink(missing_ok=True)
        target.write_text(script, encoding="utf-8")
        target.chmod(0o755)

    def ssh(
        self,
        status: str,
        *,
        status_rc: int = 0,
        ops_rc: int = 0,
        pulled: dict[str, str] | None = None,
        pulled_raw: str | None = None,
    ) -> None:
        """A canned ``ssh``: ``status.sh`` prints ``status``; other cluster scripts exit ``ops_rc``.

        ``pulled`` (tag -> digest): a successful ``ollama-op.sh pull`` then replaces ``/api/tags``;
        ``pulled_raw`` does the same with an arbitrary body (empty, not JSON, no digest).
        """
        status_file = self.root / "status.csv"
        status_file.write_text(status + "\n", encoding="utf-8")
        after = self.root / "tags-after-pull.json"
        rows = [{"name": reported(t), "digest": d} for t, d in (pulled or {}).items()]
        body = pulled_raw if pulled_raw is not None else json.dumps({"models": rows})
        after.write_text(body, encoding="utf-8")
        on_pull = (
            f"cp {shlex.quote(str(after))} {shlex.quote(str(self.tags_file))};"
            if (pulled or pulled_raw is not None)
            else ""
        )
        script = f"""#!/usr/bin/env bash
echo "ssh $*" >> {shlex.quote(str(self.stubs.log))}
case "$*" in
  *status.sh*) cat {shlex.quote(str(status_file))}; exit {status_rc};;
  *"ollama-op.sh pull"*) [ {ops_rc} -eq 0 ] && {{ {on_pull} :; }}; echo ok; exit {ops_rc};;
  *ollama-op.sh*) echo ok; exit {ops_rc};;
  *start-ollama.sh*) echo started; exit {ops_rc};;
  *stop-ollama.sh*) echo stopped; exit {ops_rc};;
  *log-tail.sh*) echo log; exit {ops_rc};;
  *) echo "UNEXPECTED ssh $*" >&2; exit 99;;
esac
"""
        target = self.stubs.bin / "ssh"
        target.unlink(missing_ok=True)
        target.write_text(script, encoding="utf-8")
        target.chmod(0o755)

    def env(self, **extra: str) -> dict[str, str]:
        """Environment of a VM script run inside the lock (``PRUEFSTAND_LOCK_HELD=1``)."""
        base = {
            "PRUEFSTAND_LOCK_HELD": "1", "PRUEFSTAND_LOCK_DIR": str(self.lock_dir),
            "PRUEFSTAND_DATA_ROOT": str(self.data_root), "PRUEFSTAND_PYTHON": sys.executable,
            "PRUEFSTAND_SERVICE_USER": getpass.getuser(), "CLUSTER_SSH_HOST": "cairo-s101lp",
            "OLLAMA_GPU0_URL": "http://127.0.0.1:11434", "OLLAMA_GPU1_URL": "http://127.0.0.1:11434",
            "REPAIR_POLL_S": "0.05", "REPAIR_WAIT_S": "3", "SERVER_WAIT_S": "3",
        }  # fmt: skip
        return {**base, **extra}

    def script(self, name: str, *args: object, **extra: str) -> Result:
        """Run ``infra/gpu/<name>`` with the healthy-world environment."""
        return run_script(GPU_DIR / name, *args, stubs=self.stubs, env=self.env(**extra))

    def posts(self) -> list[dict[str, Any]]:
        """The JSON bodies of every ``curl ... -d <body>`` call, in call order."""
        bodies = []
        for line in self.stubs.calls("curl"):
            if " -d " in line:
                bodies.append(json.loads(line.split(" -d ", 1)[1].split(" ", 1)[0]))
        return bodies
