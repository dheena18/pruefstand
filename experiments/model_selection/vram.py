"""Reads the GPU and disk figures out of ``pruefstand-cluster status``.

(T3.1a wrapper), the only cluster access.
"""

import re
import subprocess
from pathlib import Path

import yaml
from model_selection.client import MODELS_YAML

GIB = 1024**3

_GPU = re.compile(r"^gpu:(\d+),INFO,.*?used_mib=(\d+) total_mib=(\d+)$")
_DISK = re.compile(r"^disk-models,\w+,free_kb=(\d+)")
STATUS_CMD = ("sudo", "-n", "-u", "pruefstand", "/usr/local/bin/pruefstand-cluster", "status")


def parse_status(csv: str) -> dict[str, int]:
    """Return ``gpuN_used_mib``.

    ``gpuN_total_mib`` and ``disk_models_free_kb`` from the status CSV.
    """
    out: dict[str, int] = {}
    for line in csv.splitlines():
        if m := _GPU.match(line):
            out[f"gpu{m[1]}_used_mib"] = int(m[2])
            out[f"gpu{m[1]}_total_mib"] = int(m[3])
        elif m := _DISK.match(line):
            out["disk_models_free_kb"] = int(m[1])
    return out


def snapshot() -> dict[str, int]:
    """Run the wrapper and parse it (needs the VM and sudo for the wrapper; 30 s timeout)."""
    done = subprocess.run(  # noqa: S603  # reason: fixed argv, no shell, no user input
        STATUS_CMD, capture_output=True, text=True, timeout=30, check=False
    )
    return parse_status(done.stdout)


def overhead_gib(size_vram: int, disk_bytes: int) -> float:
    """Provisional overhead: resident VRAM (``/api/ps`` ``size_vram``) minus disk size, in GiB.

    It still contains the KV cache at the pinned ``num_ctx`` and slots, so it is an upper bound
    of the vision tower plus compute buffer (the load log gives the exact split).

    >>> overhead_gib(11 * GIB, 8 * GIB)
    3.0
    """
    return round((size_vram - disk_bytes) / GIB, 3)


def disk_bytes_of(tag: str, path: Path = MODELS_YAML) -> int:
    """``disk_bytes`` of the catalogue entry for ``tag`` (id or tag); ``KeyError`` if unknown."""
    for m in yaml.safe_load(path.read_text(encoding="utf-8"))["models"]:
        if tag in (m["id"], m["tag"]):
            return int(m["disk_bytes"])
    raise KeyError(tag)
