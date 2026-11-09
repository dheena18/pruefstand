"""T5.3 S5: MEMERAG-derived content (marker ``"source": "memerag"``) never leaves data/derived/."""

from pathlib import Path

from rq2.memerag_guard import find_memerag_content

REPO = Path(__file__).resolve().parents[3]
LINE = '{"item_id": "x", "metric": "faithfulness", "source": "memerag", "label": 2}\n'


def test_marker_under_datasets_fails(tmp_path: Path) -> None:
    target = tmp_path / "datasets/calibration/v1/faith.jsonl"
    target.parent.mkdir(parents=True)
    target.write_text(LINE, encoding="utf-8")
    assert find_memerag_content(tmp_path) == [Path("datasets/calibration/v1/faith.jsonl")]


def test_marker_under_apps_examples_and_hf_export_fails(tmp_path: Path) -> None:
    for rel in (
        "apps/dashboard/fixtures/a.json",
        "examples/x/b.yaml",
        "hf_export/germanquad_derived/c.jsonl",
    ):
        path = tmp_path / rel
        path.parent.mkdir(parents=True)
        path.write_text(LINE, encoding="utf-8")
    assert len(find_memerag_content(tmp_path)) == 3


def test_marker_under_data_derived_passes(tmp_path: Path) -> None:
    target = tmp_path / "data/derived/memerag_de/faithfulness_memerag.jsonl"
    target.parent.mkdir(parents=True)
    target.write_text(LINE, encoding="utf-8")
    (tmp_path / "datasets").mkdir()
    (tmp_path / "datasets/ok.jsonl").write_text('{"source": "germanquad"}\n', encoding="utf-8")
    assert find_memerag_content(tmp_path) == []


def test_repository_is_clean() -> None:
    """Runs in ``make check``: the real repository holds no MEMERAG item outside data/derived/."""
    assert find_memerag_content(REPO) == []
