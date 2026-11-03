"""``scripts/make_heldout_canaries.py``: seed from the environment, output not in git (T2.6 S7)."""

import json
import subprocess
from pathlib import Path

import pytest
from make_heldout_canaries import DEFAULT_OUT, main
from testsupport.private_docs_support import write_approved

from pruefstand.core.models.attacks import CanaryRegistry

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return write_approved(tmp_path / "approved", per_tenant=3)


def run(source: Path, out: Path, *extra: str) -> int:
    return main(["--seed-env", "HELDOUT_SEED", "--source", str(source), "--out", str(out), *extra])


def test_seed_123_builds_six_documents_and_a_registry(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HELDOUT_SEED", "123")
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
    monkeypatch.setenv("HELDOUT_SEED", "123")
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
    monkeypatch.setenv("HELDOUT_SEED", "123")
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


@pytest.mark.parametrize("value", [None, "", "abc", "-5"])
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
    monkeypatch.setenv("HELDOUT_SEED", "123")
    tracked = REPO / "datasets" / "fixtures" / "_heldout_must_not_exist"
    assert run(source, tracked) == 2
    assert not tracked.exists()
