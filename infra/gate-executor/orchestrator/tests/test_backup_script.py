"""backup.sh (T6.2b, X2.6, Y5.5, D1094): offline refusals; real `age` round trip if installed."""

import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "host" / "backup.sh"
RECIPIENT = "age1" + "q" * 58
AGE = shutil.which("age")
AGE_KEYGEN = shutil.which("age-keygen")


def _exe(name: str) -> str:
    path = shutil.which(name)
    assert path is not None, name
    return path


def _call(*argv: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  (fixed argv: our script, git, age with test paths)
        list(argv), env=env, capture_output=True, text=True, timeout=60, check=False
    )


def _run(tmp: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    base = {"PATH": os.environ["PATH"], "HOME": str(tmp)}
    return _call(_exe("bash"), str(SCRIPT), *args, env={**base, **env})


def _repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    (repo / "canaries").mkdir(parents=True)
    git = [_exe("git"), "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    assert _call(*git, "init", "-q", "-b", "main").returncode == 0
    (repo / "canaries" / "heldout.txt").write_text("Kündigungsfrist\n", encoding="utf-8")
    assert _call(*git, "add", ".").returncode == 0
    assert _call(*git, "commit", "-q", "-m", "x").returncode == 0
    return repo


@pytest.mark.parametrize("recipient", ["", "age1short", "ssh-ed25519 AAAA", "AGE1" + "Q" * 58])
def test_bad_recipient_is_refused(tmp_path: Path, recipient: str) -> None:
    root = str(tmp_path)
    proc = _run(tmp_path, "--repo", root, AGE_RECIPIENT=recipient, PRUEFSTAND_DATA_ROOT=root)
    assert proc.returncode == 2
    assert "AGE_RECIPIENT" in proc.stderr


def test_missing_data_root_fails(tmp_path: Path) -> None:
    missing = str(tmp_path / "nope")
    proc = _run(
        tmp_path, "--repo", str(tmp_path), AGE_RECIPIENT=RECIPIENT, PRUEFSTAND_DATA_ROOT=missing
    )
    assert proc.returncode == 1
    assert "data root unusable" in proc.stderr


@pytest.mark.parametrize("args", [[], ["--repo"], ["--repo", "x", "--keep", "0"], ["--bogus"]])
def test_usage_errors(tmp_path: Path, args: list[str]) -> None:
    assert _run(tmp_path, *args, AGE_RECIPIENT=RECIPIENT).returncode == 64


@pytest.mark.skipif(AGE is None or AGE_KEYGEN is None, reason="age is not installed")
def test_encrypted_bundle_round_trip_and_keep(tmp_path: Path) -> None:
    assert AGE is not None
    assert AGE_KEYGEN is not None
    key = tmp_path / "key.txt"
    assert _call(AGE_KEYGEN, "-o", str(key)).returncode == 0
    recipient = _call(AGE_KEYGEN, "-y", str(key)).stdout.strip()
    root = tmp_path / "root"
    (root / "baselines" / "fp").mkdir(parents=True)
    (root / "baselines" / "fp" / "index.json").write_text("{}", encoding="utf-8")
    for day in ("2026-01-01", "2026-01-02", "2026-01-03"):
        (root / "backups" / day).mkdir(parents=True)
    repo = str(_repo(tmp_path))
    proc = _run(
        tmp_path,
        "--repo",
        repo,
        "--keep",
        "2",
        AGE_RECIPIENT=recipient,
        PRUEFSTAND_DATA_ROOT=str(root),
    )
    assert proc.returncode == 0, proc.stderr
    dated = sorted(p.name for p in (root / "backups").iterdir())
    assert len(dated) == 2
    assert "2026-01-03" in dated
    (out,) = (root / "backups").glob("*/pruefstand-gate.bundle.tar.age")
    assert not list((root / "backups").glob("*/*.partial"))
    assert "Kündigungsfrist".encode() not in out.read_bytes()
    plain = tmp_path / "plain.tar"
    assert _call(AGE, "-d", "-i", str(key), "-o", str(plain), str(out)).returncode == 0
    with tarfile.open(plain) as tar:
        names = tar.getnames()
    assert "pruefstand-gate.bundle" in names
    assert "baselines/fp/index.json" in names


def test_dry_run_prints_one_encrypting_pipeline_and_writes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    proc = _run(
        tmp_path,
        "--repo",
        "r",
        "--dry-run",
        AGE_RECIPIENT=RECIPIENT,
        PRUEFSTAND_DATA_ROOT=str(root),
    )
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    (pipeline,) = [line for line in lines if "|" in line]
    assert pipeline.endswith(".partial")
    assert f"| age -r {RECIPIENT} -o {root}/backups/" in pipeline
    assert any(line.startswith("mv -f -- ") and line.endswith(".tar.age") for line in lines)
    assert list(root.iterdir()) == []


@pytest.mark.skipif(AGE is None, reason="age is not installed")
def test_a_failed_encryption_leaves_no_partial_file(tmp_path: Path) -> None:
    # review #214: "age1" + 58 x "q" has the right shape but a bad checksum, so age fails
    root = tmp_path / "root"
    root.mkdir()
    repo = str(_repo(tmp_path))
    proc = _run(tmp_path, "--repo", repo, AGE_RECIPIENT=RECIPIENT, PRUEFSTAND_DATA_ROOT=str(root))
    assert proc.returncode != 0
    assert list(root.glob("backups/*/*.partial")) == []
    assert list(root.glob("backups/*/*.age")) == []


@pytest.mark.skipif(AGE is None or AGE_KEYGEN is None, reason="age is not installed")
def test_a_tar_failure_after_age_started_removes_the_partial_file(tmp_path: Path) -> None:
    # review #214 follow-up: the EXIT trap itself, not an early refusal. age is real and has
    # already created and written the .partial; a `tar` shim then fails mid-stream (pipefail).
    assert AGE_KEYGEN is not None
    key = tmp_path / "key.txt"
    assert _call(AGE_KEYGEN, "-o", str(key)).returncode == 0
    recipient = _call(AGE_KEYGEN, "-y", str(key)).stdout.strip()
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "tar").write_text("#!/bin/sh\nprintf 'half a stream'\nexit 2\n", encoding="utf-8")
    (shim / "tar").chmod(0o755)
    root = tmp_path / "root"
    (root / "baselines").mkdir(parents=True)
    proc = _run(
        tmp_path,
        "--repo",
        str(_repo(tmp_path)),
        AGE_RECIPIENT=recipient,
        PRUEFSTAND_DATA_ROOT=str(root),
        PATH=f"{shim}:{os.environ['PATH']}",
    )
    assert proc.returncode != 0
    assert list(root.glob("backups/*/*.partial")) == []
    assert list(root.glob("backups/*/*.age")) == []
