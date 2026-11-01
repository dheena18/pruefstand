"""Fixtures of the ingest tests: real trimmed GII norms, zipped like the GII downloads."""

import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "gii"
RawFactory = Callable[[Mapping[str, Mapping[str, bytes]]], Path]


@pytest.fixture
def fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture
def make_raw(tmp_path: Path) -> RawFactory:
    """Build ``<raw>/<slug>/xml.zip`` from ``{slug: {member name: bytes}}`` and return ``<raw>``."""

    def build(laws: Mapping[str, Mapping[str, bytes]]) -> Path:
        raw = tmp_path / "raw"
        for slug, members in laws.items():
            target = raw / slug
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(target / "xml.zip", "w", zipfile.ZIP_DEFLATED) as zf:
                for name, data in members.items():
                    zf.writestr(name, data)
        return raw

    return build


@pytest.fixture
def raw_dir(make_raw: RawFactory) -> Path:
    """Raw directory with the five real fixture laws (BGB, KSchG, ArbZG, AktG, EGBGB)."""
    names = {
        "bgb": "bgb_sample.xml", "kschg": "kschg_1.xml", "arbzg": "arbzg_3.xml",
        "aktg": "aktg_95.xml", "egbgb": "egbgb_sample.xml",
    }  # fmt: skip
    return make_raw({slug: {name: (FIXTURE_DIR / name).read_bytes()} for slug, name in names.items()})
