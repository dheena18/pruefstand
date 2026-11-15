"""Scorecard PinnedDependencies (D1220): connect-vm.sh pins and hash-checks Tailscale."""

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "cloud" / "connect-vm.sh"
TEXT = SCRIPT.read_text(encoding="utf-8")
RETRY = "--retry 3 --retry-all-errors --retry-delay 5"
PIPE_TO_SHELL = re.compile(
    r"(\b(curl|wget)\b[^\n]*\|\s*(\$\w+\s+|sudo\s+(-\w+\s+)*)?(ba|da)?sh\b)"
    r"|((ba|da)?sh\s+(-\w+\s+)*<\(\s*(curl|wget)\b)"
)


def _code(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def test_no_pipe_from_download_to_shell() -> None:
    assert PIPE_TO_SHELL.search(_code(TEXT)) is None


def test_pipe_regex_catches_mutations() -> None:
    for bad in (
        "curl -fsSL https://x.example/i.sh | sh",
        "curl -fsSL https://x.example/i.sh | $SUDO sh",
        "curl -fsSL https://x.example/i.sh | sudo -E bash -s",
        "wget -qO- https://x.example/i.sh | bash",
        "bash <(curl -fsSL https://x.example/i.sh)",
    ):
        assert PIPE_TO_SHELL.search(bad) is not None, bad
    assert PIPE_TO_SHELL.search('echo "$H  f" | sha256sum -c -') is None


def test_script_fails_closed() -> None:
    assert "set -euo pipefail" in TEXT
    assert re.search(r'^\s*TS_SHA256="[0-9a-f]{64}"$', TEXT, re.MULTILINE)
    check = TEXT.index('if ! echo "$TS_SHA256 ')
    assert "| sha256sum -c -" in TEXT[check : check + 120]
    assert check < TEXT.index("tar -xzf")
    assert "trap 'rm -rf \"$ts_dir\"' EXIT" in TEXT


def test_download_is_version_pinned_and_retries() -> None:
    assert re.search(r'TS_VERSION="\d+\.\d+\.\d+"', TEXT)
    assert "pkgs.tailscale.com/stable/tailscale_${TS_VERSION}_amd64.tgz" in TEXT
    curls = [ln for ln in TEXT.replace("\\\n", " ").splitlines() if re.match(r"\s*curl\b", ln)]
    assert curls
    for line in curls:
        assert RETRY in line
        assert re.search(r"\bcurl -[a-zA-Z]*f", line)
