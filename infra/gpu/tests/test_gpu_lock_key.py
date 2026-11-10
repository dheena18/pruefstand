"""T3.1d CPU tests: the ``stat %D`` decode of the ``pruefstand-cluster`` wrapper (``lock_key``)."""

import re
import subprocess

import pytest
from gpu_testkit import GPU_DIR

WRAPPER = GPU_DIR / "pruefstand-cluster"


def _lock_key(dev_hex: str, inode: str) -> str:
    """Run the wrapper's own ``lock_key`` function (cut out of the file, not copied)."""
    text = WRAPPER.read_text(encoding="utf-8")
    match = re.search(r"^lock_key\(\) \{.*?^\}$", text, re.M | re.S)
    assert match, "lock_key() not found in the wrapper"
    proc = subprocess.run(  # noqa: S603
        ["bash", "-c", f'{match.group(0)}\nlock_key "$1" "$2"', "x", dev_hex, inode],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return proc.stdout


@pytest.mark.parametrize(
    ("dev_hex", "expected"),
    [
        ("10002c", "00:12c:7"),  # minor 300 (above 255): bits 0-7 and 20-31 of dev_t
        ("801", "08:01:7"),  # classic sda1
        ("fd01", "fd:01:7"),  # device mapper style
        ("fe00", "fe:00:7"),
        (
            "100000000001",
            "1000:01:7",
        ),  # major above 4095 uses bits 32+, which must not leak into the minor
    ],
)
def test_stat_dev_decodes_to_the_key_proc_locks_prints(dev_hex: str, expected: str) -> None:
    assert _lock_key(dev_hex, "7") == expected


def test_the_inode_is_passed_through_unchanged() -> None:
    assert _lock_key("801", "131074") == "08:01:131074"
