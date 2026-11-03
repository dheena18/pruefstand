"""In-domain near-miss refusals over the committed slice corpus (T4.6 S3, D9-31)."""

import json
from pathlib import Path

import numpy as np
import pytest

from pruefstand.attacks.refusal import CITE_TAG, NEAR_MISS_TAG, make_own_unanswerable
from pruefstand.core.errors import DatasetError

SLICE = Path(__file__).resolve().parents[5] / "corpus" / "slice_v1"
TENANTS = ("kanzlei_mueller", "versicherung_nord", "stadtwerke_sued")


def _keys(tenant: str) -> set[str]:
    lines = (SLICE / f"{tenant}.chunks.jsonl").read_text("utf-8").splitlines()
    return {k for k in (json.loads(x).get("citation_key") for x in lines) if k}


def indexed() -> dict[str, frozenset[str]]:
    shared = _keys("shared_public")
    return {t: frozenset(_keys(t) | shared) for t in TENANTS}


def test_at_least_half_are_near_misses_and_every_named_section_is_absent() -> None:
    keys = indexed()
    cases = make_own_unanswerable(keys, np.random.default_rng(2))
    near = [c for c in cases if NEAR_MISS_TAG in c.tags]
    assert len(near) * 2 >= len(cases)
    for tenant in TENANTS:
        mine = [c for c in cases if c.tenant == tenant]
        assert len([c for c in mine if NEAR_MISS_TAG in c.tags]) * 2 >= len(mine)
    cited = 0
    for case in near:
        for tag in case.tags:
            if tag.startswith(CITE_TAG):
                cited += 1
                assert tag.removeprefix(CITE_TAG) not in keys[case.tenant], (case.id, tag)
    assert cited * 2 >= len(near)


def test_a_template_naming_an_indexed_section_is_refused() -> None:
    keys = indexed()
    keys["kanzlei_mueller"] = frozenset({*keys["kanzlei_mueller"], "§ 30 KSchG"})
    with pytest.raises(DatasetError, match="30 KSchG"):
        make_own_unanswerable(keys, np.random.default_rng(2))
