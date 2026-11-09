"""The spot-check app renders three real slice items and writes decisions (T4.7a)."""

import json
from pathlib import Path

import pytest
import yaml
from streamlit.testing.v1 import AppTest
from testsupport.build_support import SLICE_DIR, candidates
from testsupport.qa_support import slice_chunks

from pruefstand.core.config import DatasetBuildConfig
from pruefstand.core.enums import Split
from pruefstand.core.ids import ChunkId
from pruefstand.dataset.io import build_manifest, write_dataset
from pruefstand.pipeline.build_perturb import base_cases
from pruefstand.pipeline.review_run import SPOT_DECISIONS, SPOT_SAMPLE, dataset_dir, review_dir

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DatasetBuildConfig:
    cands = [
        c for c in candidates() if c.chunk_id in {"gii-bgb-622#2", "gii-arbzg-3#0", "gii-bgb-623#0"}
    ]
    cases, _ = base_cases(
        cands, {ChunkId(k): v for k, v in slice_chunks().items()}, "slice-2026-10-31.51fd4b94"
    )
    smoke = [c.model_copy(update={"split": Split.SMOKE}) for c in cases]
    cfg = DatasetBuildConfig(
        name="pruefstand-de-small", dataset_version="v1", corpus_dir=SLICE_DIR,
        out_dir=tmp_path / "datasets" / "fixtures", work_dir=tmp_path / "work", seed=1,
    )  # fmt: skip
    manifest = build_manifest(
        cfg.name, cfg.dataset_version, "slice-2026-10-31.51fd4b94", smoke, seed=1
    )
    write_dataset(dataset_dir(cfg), smoke, manifest)
    review_dir(cfg).mkdir(parents=True)
    (review_dir(cfg) / SPOT_SAMPLE).write_text(
        "".join(json.dumps({"id": c.id}) + "\n" for c in smoke), encoding="utf-8"
    )
    path = tmp_path / "dataset.yaml"
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setenv("REVIEW_APP_CONFIG", str(path))
    return cfg


def _text(app: AppTest) -> str:
    return " ".join(m.value for m in app.markdown) + " ".join(s.value for s in app.subheader)


def test_the_app_shows_the_item_and_the_highlighted_source(config: DatasetBuildConfig) -> None:
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    text = _text(app)
    assert "Question" in text
    assert "Source text" in text
    assert "background:#fff3b0" in text or "background:#ffd24a" in text  # a highlighted Absatz
    assert "0 of 3 checked" in " ".join(c.value for c in app.caption)


def test_the_app_needs_a_pseudonym_before_it_asks(config: DatasetBuildConfig) -> None:
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert any("pseudonym" in w.value for w in app.warning)
    assert not app.button


def test_two_answers_write_one_decision_line(config: DatasetBuildConfig) -> None:
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.session_state["pseudonym"] = "anna"
    app.run()
    app.button(key="c_yes").click().run()
    assert any("plausible" in m.value for m in app.markdown)
    app.button(key="p_no").click().run()
    lines = (review_dir(config) / SPOT_DECISIONS).read_text("utf-8").splitlines()
    (row,) = [json.loads(x) for x in lines]
    assert row["citation_ok"] is True
    assert row["plausible"] is False
    assert row["reviewer"] == "owner-spotcheck:anna"
    assert {"case_id", "note", "ts"} <= set(row)
    assert "1 of 3 checked" in " ".join(c.value for c in app.caption)


def test_the_app_never_writes_into_the_dataset_directory(config: DatasetBuildConfig) -> None:
    before = {p.name: p.read_bytes() for p in dataset_dir(config).iterdir()}
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.session_state["pseudonym"] = "anna"
    app.run()
    app.button(key="c_no").click().run()
    app.button(key="p_no").click().run()
    assert {p.name: p.read_bytes() for p in dataset_dir(config).iterdir()} == before
