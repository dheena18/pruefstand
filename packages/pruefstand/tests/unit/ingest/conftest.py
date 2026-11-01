"""Fixtures of the ingest tests: real trimmed GII norms, zipped like the GII downloads."""

import json
import zipfile
from collections.abc import Callable, Mapping, Sequence
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
    return make_raw(
        {slug: {name: (FIXTURE_DIR / name).read_bytes()} for slug, name in names.items()}
    )


# --- T2.3: OLDP decisions (three real trimmed records of the pinned 1k sample, see tests/fixtures/oldp) ---

OLDP_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "oldp"
OLDP_GRAPH_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "oldp_graph"
OLDP_STEMS = ("labour_lag_hessen", "insurance_ag_duesseldorf", "noheadings_ovg_sachsen")
OldpRecord = Callable[[str], dict[str, object]]
JsonlWriter = Callable[[Path, Sequence[Mapping[str, object]]], Path]


def _record(stem: str) -> dict[str, object]:
    loaded: dict[str, object] = json.loads((OLDP_FIXTURES / f"{stem}.json").read_text("utf-8"))
    return loaded


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    path.write_text(lines, encoding="utf-8")
    return path


@pytest.fixture
def oldp_record() -> OldpRecord:
    """Return the fixture record of a stem (``labour_lag_hessen``, ...) as a dict."""
    return _record


@pytest.fixture
def write_jsonl() -> JsonlWriter:
    """Write rows as UTF-8 JSON lines and return the path."""
    return _write_jsonl


@pytest.fixture
def oldp_raw(tmp_path: Path) -> Path:
    """``<tmp>/hf/oldp_decisions`` holding the three fixture decisions as one JSONL file."""
    target = tmp_path / "hf" / "oldp_decisions"
    _write_jsonl(target / "decisions.jsonl", [_record(s) for s in OLDP_STEMS])
    return target


@pytest.fixture
def oldp_graph_raw(oldp_raw: Path) -> Path:
    """``<tmp>/hf/oldp_citation_graph`` (sibling of :func:`oldp_raw`) with the fixture edges."""
    target = oldp_raw.parent / "oldp_citation_graph"
    target.mkdir()
    (target / "edges.jsonl").write_bytes((OLDP_GRAPH_FIXTURES / "edges.jsonl").read_bytes())
    return target
