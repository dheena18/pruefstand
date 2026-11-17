"""scripts/deploy/build_leak_probe_set.py: the probe dataset of the pre-deploy gate (T8.5 S6)."""

import json
import re
from pathlib import Path

import pytest
from deploy.build_leak_probe_set import DEFAULT_FIXTURES, DEFAULT_REGISTRY, main

from pruefstand.core.enums import Category, Split
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import read_dataset

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = [ROOT / p for p in DEFAULT_FIXTURES]
REGISTRY = ROOT / DEFAULT_REGISTRY
PROBE = {Category.LEAK_PROBE, Category.FILTER_BYPASS, Category.SYSTEM_PROMPT_EXTRACTION}


def _build(out: Path) -> list[TestCase]:
    argv = ["--out", str(out), "--corpus-version", "slice-test", "--registry", str(REGISTRY)]
    assert main([*argv, "--fixtures", *map(str, FIXTURES)]) == 0
    return read_dataset(out).cases[Split.FULL]


def test_the_set_holds_every_fixture_probe_and_the_generated_probes(tmp_path: Path) -> None:
    cases = _build(tmp_path / "set")
    ids = {c.id for c in cases}
    for directory in FIXTURES:
        for split in read_dataset(directory).cases.values():
            assert {c.id for c in split if c.category in PROBE} <= ids
    generated = [c for c in cases if c.source.startswith("attacks:")]
    assert {c.category for c in generated} == PROBE
    # the customer tenants of the public registry each ask and are asked about
    askers = {c.tenant for c in generated if c.category is Category.LEAK_PROBE}
    assert askers == {"kanzlei_mueller", "versicherung_nord"}
    assert {c.category for c in cases} == PROBE


def test_everything_is_stamped_and_in_the_full_split(tmp_path: Path) -> None:
    cases = _build(tmp_path / "set")
    assert {c.split for c in cases} == {Split.FULL}
    assert {c.corpus_version for c in cases} == {"slice-test"}
    assert len({c.id for c in cases}) == len(cases)


def test_a_held_out_registry_is_refused_before_anything_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    heldout = tmp_path / "canaries.json"
    heldout.write_text(REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    code = main(
        ["--out", str(tmp_path / "set"), "--corpus-version", "v", "--registry", str(heldout)]
    )
    assert code == 2
    assert "not a public registry" in capsys.readouterr().err
    assert not (tmp_path / "set").exists()


def test_no_token_outside_the_public_registry_reaches_the_set(tmp_path: Path) -> None:
    _build(tmp_path / "set")
    text = "\n".join(p.read_text(encoding="utf-8") for p in (tmp_path / "set").glob("*.jsonl"))
    public = {c["token"] for c in json.loads(REGISTRY.read_text(encoding="utf-8"))["canaries"]}
    for token in set(re.findall(r"CANARY-[A-Z0-9]+-[0-9a-f]+", text)):
        assert token in public
