"""runner-env-keys.sh adds the executor Qdrant's read-only key to runner.env (D1281, D1098)."""

import re
import stat
import subprocess
from pathlib import Path

KEYS = Path(__file__).resolve().parents[2] / "host" / "runner-env-keys.sh"
NAME = "QDRANT_READ_ONLY_API_KEY"


def run_from_stdin(path: Path) -> subprocess.CompletedProcess[str]:
    """As the owner runs it: the script on stdin, the file as the one argument."""
    return subprocess.run(  # noqa: S603
        ["bash", "-s", "--", str(path)],  # noqa: S607
        input=KEYS.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_an_existing_runner_env_gets_only_the_read_only_key(tmp_path: Path) -> None:
    path = tmp_path / "runner.env"
    before = (
        "QDRANT_API_KEY=rw-key-kept\n"
        "PRUEFSTAND_NONCE_KEY=" + "a" * 64 + "\n"
        "PRUEFSTAND_CANDIDATE_API_KEY=" + "b" * 64 + "\n"
    )
    path.write_text(before, encoding="utf-8")
    path.chmod(0o600)
    done = run_from_stdin(path)
    assert done.returncode == 0, done.stderr
    after = path.read_text(encoding="utf-8")
    assert after.startswith(before)  # no existing line changed
    (added,) = after[len(before) :].splitlines()
    name, value = added.split("=", 1)
    assert name == NAME
    assert re.fullmatch(r"[0-9a-f]{64}", value)
    assert value not in done.stdout + done.stderr
    assert value != "rw-key-kept"  # its own key, never a copy of the read-write one
    assert f"{NAME}: added" in done.stdout
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    again = run_from_stdin(path)
    assert again.returncode == 0
    assert path.read_text(encoding="utf-8") == after  # never overwritten
    assert f"{NAME}: present, kept" in again.stdout


def test_an_empty_read_only_key_line_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "runner.env"
    path.write_text(f"{NAME}=\n", encoding="utf-8")
    path.chmod(0o600)
    done = run_from_stdin(path)
    assert done.returncode == 2
    assert f"{NAME} is present with an empty value" in done.stderr
    assert path.read_text(encoding="utf-8") == f"{NAME}=\n"
