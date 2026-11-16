"""T5.4b review: listed sentence pairs exist; the sensitivity table leaves out the invalid."""

from pathlib import Path

import pytest
from rq2.make_degraded import load_pairs
from rq2.negate_review import invalid_negations, load_review

from pruefstand.core.errors import ConfigError


def test_every_reviewed_id_is_a_committed_sentence_pair() -> None:
    review = load_review()
    sentence = {str(p["pair_id"]) for p in load_pairs() if p.get("form") == "sentence"}
    listed = set(review["invalid"]) | set(review["borderline"])
    assert listed <= sentence
    assert len(review["invalid"]) == 0  # T5.4b2: the 6 invalid pairs of T5.4b are gone (D1300)
    assert len(review["borderline"]) == 5
    assert not set(review["invalid"]) & set(review["borderline"])
    assert invalid_negations() == frozenset(review["invalid"])


def test_a_malformed_review_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="missing"):
        load_review(tmp_path / "none.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("invalid: [a]\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mappings"):
        load_review(bad)
