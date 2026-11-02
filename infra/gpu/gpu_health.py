"""Analysis half of ``health.sh``: residency, digests, placement, VRAM, disk, cluster scripts.

The shell collects the facts (curl, ssh, df) and writes them to files; this module turns them
into the CSV rows ``check,status,detail`` and the exit codes of interfaces 1.5 (10 low free VRAM,
11 a model/endpoint missing, 13 digest differs, 14 cluster bin dir out of date, 15 not fully on the
GPU or spread over both cards). Codes 12 (status.sh unreachable) and 16 (data root) are decided by
the shell. Output: the rows, then
one line ``CODES:<comma separated>``.
"""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import gpu_catalogue as cat

Row = tuple[str, str, str]
LOW_VRAM, MISSING, DIGEST, BIN_OLD, NOT_ON_GPU = 10, 11, 13, 14, 15
KV = re.compile(r"(\w+)=(\S+)")


def parse_status(text: str) -> dict[str, tuple[str, str]]:
    """``status.sh`` CSV -> {check: (status, detail)}; the header and bad lines are skipped."""
    rows: dict[str, tuple[str, str]] = {}
    for line in text.splitlines()[1:]:
        parts = line.split(",", 2)
        if len(parts) == 3:
            rows[parts[0]] = (parts[1], parts[2])
    return rows


def residency(
    mode: str, resident: dict[str, tuple[str, int, int]], status: dict[str, tuple[str, str]]
) -> tuple[list[Row], set[int]]:
    """Rows and codes for the models of the mode: resident, digest, fully in VRAM, one card."""
    rows: list[Row] = []
    codes: set[int] = set()
    for entry in cat.mode_set(mode):
        tag = entry["tag"]
        if tag not in resident:
            rows.append((f"resident:{tag}", "FAIL", "not resident (health.sh --repair loads it)"))
            codes.add(MISSING)
            continue
        digest, size, vram = resident[tag]
        if digest != entry["digest"]:
            rows.append(
                (f"resident:{tag}", "FAIL", f"digest {digest[:12]} differs from the catalogue")
            )
            codes.add(DIGEST)
        else:
            rows.append((f"resident:{tag}", "OK", f"digest {digest[:12]}"))
        row = status.get(f"placement:{tag}") or status.get(f"placement:{cat.normalise(tag)}")
        card = row[1] if row else "gpu=unknown"
        if vram < size:
            rows.append(
                (
                    f"placement:{tag}",
                    "FAIL",
                    f"size_vram {vram} < size {size}: not fully on the GPU",
                )
            )
            codes.add(NOT_ON_GPU)
        elif "+" in card:
            rows.append((f"placement:{tag}", "FAIL", f"{card}: spread over both cards"))
            codes.add(NOT_ON_GPU)
        else:
            rows.append((f"placement:{tag}", "OK", card.split()[0]))
    return rows, codes


def extras(mode: str, resident: dict[str, tuple[str, int, int]]) -> list[Row]:
    """WARN rows for resident models outside the mode (--repair unloads catalogue ones)."""
    wanted = {e["tag"] for e in cat.mode_set(mode)}
    known = {e["tag"] for e in cat.ollama_entries()}
    rows: list[Row] = []
    for tag in sorted(set(resident) - wanted):
        why = (
            "catalogue model outside the mode (--repair unloads it)"
            if tag in known
            else "not a catalogue model (left alone)"
        )
        rows.append((f"extra:{tag}", "WARN", why))
    return rows


def vram_rows(status: dict[str, tuple[str, str]], min_free_mib: int) -> tuple[list[Row], set[int]]:
    """Free VRAM per card from the ``gpu:<i>`` rows of ``status.sh``."""
    rows: list[Row] = []
    codes: set[int] = set()
    for check, (_, detail) in sorted(status.items()):
        if not check.startswith("gpu:"):
            continue
        kv = dict(KV.findall(detail))
        free = int(kv.get("total_mib", 0)) - int(kv.get("used_mib", 0))
        ok = free >= min_free_mib
        rows.append(
            (
                f"vram:{check[4:]}",
                "OK" if ok else "FAIL",
                f"free_mib={free} min_free_mib={min_free_mib}",
            )
        )
        if not ok:
            codes.add(LOW_VRAM)
    return rows, codes


def cluster_rows(
    status: dict[str, tuple[str, str]], expected_sums: str
) -> tuple[list[Row], set[int]]:
    """Pass-through rows (env, disk, foreign GPU processes) and the bin-dir checks (exit 14)."""
    rows: list[Row] = []
    codes: set[int] = set()
    for check, (state, detail) in sorted(status.items()):
        if (
            check in {"disk-models", "start-script"}
            or check.startswith("env")
            or (check.startswith("gpu-proc:") and state == "WARN")
        ):
            rows.append((check, state, detail))
        if check == "second-server":
            rows.append((check, "FAIL", detail))
            codes.add(MISSING)
    integrity = status.get("bin-integrity", ("FAIL", "missing"))
    sums = dict(KV.findall(status.get("bin-sums", ("", ""))[1])).get("sha256", "")
    if integrity[0] != "OK" or not expected_sums or sums != expected_sums:
        reason = (
            integrity[1] if integrity[0] != "OK" else "cluster scripts differ from this checkout"
        )
        rows.append(("bin-dir", "FAIL", f"{reason}; run deploy-cluster-bin.sh"))
        codes.add(BIN_OLD)
    else:
        rows.append(("bin-dir", "OK", "scripts match the checkout"))
    return rows, codes


def load_resident(files: Sequence[Path]) -> dict[str, tuple[str, int, int]]:
    """Merge the ``/api/ps`` bodies: tag -> (digest, size, size_vram)."""
    out: dict[str, tuple[str, int, int]] = {}
    for file in files:
        for name, digest, _ctx, size, vram in cat.ps_rows(file.read_text(encoding="utf-8")):
            out[name] = (digest, int(size), int(vram))
    return out


def analyse(args: argparse.Namespace) -> tuple[list[Row], set[int]]:
    """All rows and codes of one health run."""
    resident = load_resident(args.ps)
    status = parse_status(args.status.read_text(encoding="utf-8"))
    rows, codes = residency(args.mode, resident, status)
    rows += extras(args.mode, resident)
    for more_rows, more_codes in (
        vram_rows(status, args.min_free_vram_mib),
        cluster_rows(status, args.expected_sums),
    ):
        rows += more_rows
        codes |= more_codes
    return rows, codes


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--ps", type=Path, nargs="+", required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--expected-sums", default="")
    parser.add_argument("--min-free-vram-mib", type=int, default=1024)
    args = parser.parse_args(argv)
    try:
        rows, codes = analyse(args)
    except cat.UsageError as err:
        sys.stderr.write(f"gpu_health: {err}\n")
        return err.code
    sys.stdout.write("".join(f"{c},{s},{d.replace(',', ';')}\n" for c, s, d in rows))
    sys.stdout.write("CODES:" + ",".join(str(c) for c in sorted(codes)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
