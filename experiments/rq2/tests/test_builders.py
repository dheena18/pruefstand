"""T5.3 S3/S4: set builders on real rows (GermanQuAD test, GermanRAG, MEMERAG if downloaded)."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from rq2 import build_calibration_sets as cli
from rq2.calib_memerag import build_memerag, memerag_item
from rq2.calib_quad import (
    annotators_agree,
    build_consistency,
    build_correctness,
    correctness_hard,
    sample_questions,
)
from rq2.calib_rag import build_faithfulness_constructed, build_refusal
from rq2.calib_schema import MAX_LABEL, CalibrationItem
from rq2.calib_sources import (
    MEMERAG_DIR,
    QuadRow,
    RagRow,
    load_germanquad,
    load_germanrag,
    load_memerag,
)
from rq2.calib_split import positive_share
from rq2.construct import REFUSALS, norm
from rq2.memerag_guard import MARKER

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[3]
SEED = 1234
CONSTRUCTED = {"same_paragraph_span", "number_date_swap", "negation_flip", "partial_answer"}


@pytest.fixture(scope="module")
def quad() -> list[QuadRow]:
    return load_germanquad(FIXTURES / "germanquad_test_6.jsonl")


@pytest.fixture(scope="module")
def rag() -> list[RagRow]:
    return load_germanrag(FIXTURES / "germanrag_4.jsonl")


def _correctness(quad: list[QuadRow]) -> list[CalibrationItem]:
    return build_correctness(sample_questions(quad, SEED), quad, SEED)


def test_correctness_is_deterministic(quad: list[QuadRow]) -> None:
    assert _correctness(quad) == _correctness(quad)


def test_correctness_labels_and_tags(quad: list[QuadRow]) -> None:
    items = _correctness(quad)
    for it in items:
        assert it.cluster_id.startswith("germanquad:")
        assert set(it.inputs) == {"frage", "referenz", "antwort"}
        if it.construction == "annotator_answer_2":
            assert it.label == 2
        elif it.construction == "partial_answer":
            assert it.label == 1
        else:
            assert it.label == 0
            ref, cand = norm(it.inputs["referenz"]), norm(it.inputs["antwort"])
            assert cand not in ref
        if it.hard_negative:
            assert it.hard_type is not None
    assert positive_share(items) == 0.5


def test_correctness_hard_types(quad: list[QuadRow]) -> None:
    rng = np.random.default_rng(SEED)
    built = {it.hard_type for row in quad for it in correctness_hard(row, rng)}
    assert built == CONSTRUCTED
    kept = {it.hard_type for it in _correctness(quad) if it.hard_negative}
    assert kept <= CONSTRUCTED
    assert len(kept) >= 3  # round-robin over types when down-sampling


def test_disagreeing_annotators_give_no_positive(quad: list[QuadRow]) -> None:
    assert annotators_agree("Am 26. März 1871", "26. März 1871")
    assert not annotators_agree("1907", "Zusammenschluss des City and Guilds College")


def test_consistency(quad: list[QuadRow]) -> None:
    rows = sample_questions(quad, SEED)
    items = build_consistency(rows, quad, SEED)
    assert items == build_consistency(rows, quad, SEED)
    kinds = {(it.construction, it.label) for it in items}
    assert {("frame", 1), ("other_question", 0), ("number_date_swap", 0)} <= kinds
    for it in items:
        assert it.metric == "perturbation_consistency"
        if it.construction == "annotator_answer_2":
            assert norm(it.inputs["antwort"]) != norm(it.inputs["referenz"])


def test_faithfulness_constructed(rag: list[RagRow]) -> None:
    items = build_faithfulness_constructed(rag, SEED)
    assert items == build_faithfulness_constructed(rag, SEED)
    assert positive_share(items) == 0.5
    for it in items:
        assert set(it.inputs) == {"frage", "kontext", "antwort"}
        if it.construction == "unsupported_context":
            assert norm(it.inputs["antwort"]) not in norm(it.inputs["kontext"])
        if it.hard_negative:
            assert it.hard_type in {"number_date_swap", "negation_flip", "partial_answer"}


def test_refusal_on_two_real_rows(rag: list[RagRow]) -> None:
    rows = [next(r for r in rag if r.answerable), next(r for r in rag if not r.answerable)]
    items = build_refusal(rows, SEED)
    assert items == build_refusal(rows, SEED)
    assert len(items) == 4
    for it in items:
        assert "erwartet" not in it.inputs
        assert set(it.inputs) == {"frage", "antwort"}
        if it.inputs["antwort"] in REFUSALS:
            assert it.label == 1
        else:
            assert it.label == 0
    assert {it.construction for it in items if it.label == 0} == {"gold_answer", "hedged_answer"}
    assert [it.hard_type for it in items if it.hard_negative] == ["hedged_answer"]


def _memerag_rows() -> dict[str, list[dict[str, Any]]]:
    variants = load_memerag(REPO / MEMERAG_DIR)
    if not variants:
        pytest.skip("MEMERAG not downloaded (data/download.py --only memerag); never committed")
    return variants


def _first(rows: list[dict[str, Any]], pred: Callable[[list[Any]], bool]) -> dict[str, Any]:
    return next(r for r in rows if pred([s["factuality"] for s in r["answer"]]))


def test_memerag_aggregation_on_three_real_rows() -> None:
    rows = _memerag_rows()["memerag"]
    supported = _first(rows, lambda fs: all(f == "Supported" for f in fs))
    not_sup = _first(rows, lambda fs: "Not Supported" in fs)
    challenging = _first(
        rows, lambda fs: "Challenging to determine" in fs and "Not Supported" not in fs
    )
    positive = memerag_item(supported, "memerag")
    assert positive is not None
    assert positive.label == 2
    item = memerag_item(not_sup, "memerag")
    assert item is not None
    assert item.label == 0
    assert item.hard_type == "memerag_not_supported"
    assert item.source == "memerag"
    assert memerag_item(challenging, "memerag") is None


def test_memerag_majority_file() -> None:
    items = build_memerag(_memerag_rows())
    assert len({(it.inputs["frage"], it.inputs["antwort"]) for it in items}) == len(items)
    assert {it.construction for it in items} == {"memerag_ext_majority", "memerag"}


def test_cli_forces_memerag_to_data_derived(tmp_path: Path) -> None:
    item = CalibrationItem(
        item_id="faithfulness_memerag:x", metric="faithfulness", cluster_id="memerag:1",
        inputs={"frage": "F", "kontext": "K", "antwort": "A"}, label=MAX_LABEL["faithfulness"],
        source="memerag", construction="memerag", calib_split="test",
    )  # fmt: skip
    other = item.model_copy(update={"item_id": "refusal:x", "metric": "refusal_judged",
                                    "inputs": {"frage": "F", "antwort": "A"}, "label": 1,
                                    "source": "germanrag"})  # fmt: skip
    sets = {"faithfulness_memerag": [item], "refusal": [other]}
    out, derived = tmp_path / "datasets/calibration/v1", tmp_path / "data/derived/memerag_de"
    out.mkdir(parents=True)
    derived.mkdir(parents=True)
    doc = cli.write_all(sets, out, derived)
    assert not (out / "faithfulness_memerag.jsonl").exists()
    assert MARKER.search((derived / "faithfulness_memerag.jsonl").read_text(encoding="utf-8"))
    published = (out / "stats.json").read_text(encoding="utf-8")
    assert not MARKER.search(published)
    assert doc["sets"]["refusal"]["calib_split"] == {"test": 1}
    assert json.loads(published)["sets"]["faithfulness_memerag"]["n_items"] == 1
