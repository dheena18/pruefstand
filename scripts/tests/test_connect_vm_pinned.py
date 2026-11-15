"""Scorecard PinnedDependencies (D1220): connect-vm.sh pins and hash-checks Tailscale."""

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "cloud" / "connect-vm.sh"
TEXT = SCRIPT.read_text(encoding="utf-8")
RETRY = "--retry 3 --retry-all-errors --retry-delay 5"


def test_no_pipe_from_download_to_shell() -> None:
    code = "\n".join(ln for ln in TEXT.splitlines() if not ln.lstrip().startswith("#"))
    assert not re.search(r"\b(curl|wget)\b[^\n]*\|\s*(\$\w+\s+)?(sudo\s+)?(ba)?sh\b", code)


def test_pinned_sha256_is_checked_before_unpacking() -> None:
    match = re.search(r'^\s*TS_SHA256="([0-9a-f]{64})"$', TEXT, re.MULTILINE)
    assert match is not None
    assert TEXT.index("sha256sum -c") < TEXT.index("tar -xzf")


def test_download_is_version_pinned_and_retries() -> None:
    assert re.search(r'TS_VERSION="\d+\.\d+\.\d+"', TEXT)
    assert "pkgs.tailscale.com/stable/tailscale_${TS_VERSION}_amd64.tgz" in TEXT
    for line in TEXT.replace("\\\n", " ").splitlines():
        if re.match(r"\s*curl\b", line):
            assert RETRY in line
