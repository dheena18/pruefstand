"""``scripts/make_heldout_canaries.py``: seed from the environment, output not in git (T2.6 S7)."""

import json
import subprocess
from pathlib import Path

import pytest
from make_heldout_canaries import DEFAULT_OUT, main
from testsupport.private_docs_support import write_approved

from pruefstand.core.models.attacks import CanaryRegistry

SEED = "3fa9c1d27b0e4a56" * 4  # 256 bits, synthetic test value
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return write_approved(tmp_path / "approved", per_tenant=3)


def run(source: Path, out: Path, *extra: str) -> int:
    return main(["--seed-env", "HELDOUT_SEED", "--source", str(source), "--out", str(out), *extra])


def test_a_256_bit_seed_builds_six_documents_and_a_registry(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HELDOUT_SEED", SEED)
    out = tmp_path / "heldout"
    assert run(source, out, "--allow-tracked") == 0
    assert len(list((out / "docs").glob("*.md"))) == 6
    registry = CanaryRegistry.model_validate_json(
        (out / "canaries_heldout.json").read_text("utf-8")
    )
    assert len(registry.canaries) == 12
    public = json.dumps(
        [
            c.token
            for p in source.rglob("*.md")
            for c in registry.canaries
            if c.token in p.read_text("utf-8")
        ]
    )
    assert public == "[]"


def test_same_seed_same_bytes(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HELDOUT_SEED", SEED)
    assert run(source, tmp_path / "a", "--allow-tracked") == 0
    assert run(source, tmp_path / "b", "--allow-tracked") == 0
    names = sorted(
        p.relative_to(tmp_path / "a") for p in (tmp_path / "a").rglob("*") if p.is_file()
    )
    assert names
    assert all(
        (tmp_path / "a" / n).read_bytes() == (tmp_path / "b" / n).read_bytes() for n in names
    )


def test_public_registry_tokens_are_avoided(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HELDOUT_SEED", SEED)
    assert run(source, tmp_path / "a", "--allow-tracked") == 0
    first = CanaryRegistry.model_validate_json(
        (tmp_path / "a" / "canaries_heldout.json").read_text("utf-8")
    )
    taken = first.canaries[0]
    public = tmp_path / "public.json"
    public.write_text(CanaryRegistry(canaries=(taken,)).model_dump_json(), "utf-8")
    assert run(source, tmp_path / "b", "--allow-tracked", "--public-registry", str(public)) == 0
    second = CanaryRegistry.model_validate_json(
        (tmp_path / "b" / "canaries_heldout.json").read_text("utf-8")
    )
    assert taken.token not in {c.token for c in second.canaries}


@pytest.mark.parametrize("value", [None, "", "abc", "-5", "123", "9" * 38, "f" * 31])
def test_a_missing_or_invalid_seed_is_refused_without_echoing_it(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str | None,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    monkeypatch.delenv("HELDOUT_SEED", raising=False)
    if value is not None:
        monkeypatch.setenv("HELDOUT_SEED", value)
    assert run(source, tmp_path / "o", "--allow-tracked") == 2
    assert "HELDOUT_SEED" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_the_default_output_is_git_ignored_and_tracked_paths_are_refused(
    source: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert DEFAULT_OUT == REPO / "datasets" / "private" / "heldout"
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "datasets/private/heldout/canaries_heldout.json"],  # noqa: S607
        cwd=REPO,
        check=False,
    )
    assert ignored.returncode == 0
    monkeypatch.setenv("HELDOUT_SEED", SEED)
    tracked = REPO / "datasets" / "fixtures" / "_heldout_must_not_exist"
    assert run(source, tracked) == 2
    assert not tracked.exists()


def test_a_128_bit_hex_seed_is_accepted(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HELDOUT_SEED", "a" * 32)
    assert run(source, tmp_path / "o", "--allow-tracked") == 0


def test_no_heldout_token_or_fact_appears_in_a_tracked_file(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HELDOUT_SEED", SEED)
    assert run(source, tmp_path / "o", "--allow-tracked") == 0
    registry = CanaryRegistry.model_validate_json(
        (tmp_path / "o" / "canaries_heldout.json").read_text("utf-8")
    )
    needles = {c.token for c in registry.canaries} | {c.fact for c in registry.canaries if c.fact}
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607
        cwd=REPO,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    for name in filter(None, tracked):
        path = REPO / name.decode()
        if path.is_file() and path.stat().st_size < 5_000_000:
            text = path.read_text("utf-8", errors="ignore")
            assert not [n for n in needles if n in text], name


def test_every_file_of_the_output_folder_must_be_ignored(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)  # noqa: S603, S607
    (repo / ".gitignore").write_text("out/canaries_heldout.json\n", encoding="utf-8")
    monkeypatch.setenv("HELDOUT_SEED", SEED)
    assert run(source, repo / "out") == 2  # docs/*.md would be tracked
    assert not (repo / "out" / "docs").exists()
    (repo / ".gitignore").write_text("out/\n", encoding="utf-8")
    assert run(source, repo / "out") == 0
