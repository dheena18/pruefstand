"""Canary rotation and the retired list (T4.6 S6)."""

import json
from pathlib import Path

import numpy as np
import pytest
from testsupport.attack_support import registry_3_tenants

from pruefstand.attacks.rotation import load_retired, retire, rotate_canaries
from pruefstand.core.errors import DatasetError

REPO = Path(__file__).resolve().parents[5]


def test_all_tokens_are_new_and_the_old_ones_are_returned_as_retired() -> None:
    old = registry_3_tenants()
    new, retired = rotate_canaries(old, "v2", np.random.default_rng(4))
    assert retired == list(old.canaries)
    assert len(new.canaries) == len(old.canaries)
    assert {c.token for c in new.canaries}.isdisjoint({c.token for c in old.canaries})
    for before, after in zip(old.canaries, new.canaries, strict=True):
        assert (after.tenant, after.doc_id, after.kind) == (
            before.tenant,
            before.doc_id,
            before.kind,
        )
        if after.kind == "token":
            assert after.forbidden_answer == after.token
            assert after.token.startswith(before.token[:10])
        else:
            assert after.fact is not None
            assert after.fact != before.fact
            assert after.forbidden_answer != before.forbidden_answer


def test_same_release_and_seed_give_the_same_tokens_other_release_other_tokens() -> None:
    old = registry_3_tenants()
    a, _ = rotate_canaries(old, "v2", np.random.default_rng(4))
    b, _ = rotate_canaries(old, "v2", np.random.default_rng(4))
    c, _ = rotate_canaries(old, "v3", np.random.default_rng(4))
    assert a == b
    assert [x.token for x in a.canaries] != [x.token for x in c.canaries]


def test_blank_release_is_refused() -> None:
    with pytest.raises(DatasetError, match="release"):
        rotate_canaries(registry_3_tenants(), " ", np.random.default_rng(1))


def test_retire_appends_and_the_file_is_checked(tmp_path: Path) -> None:
    path = tmp_path / "retired.json"
    path.write_text("[]\n", encoding="utf-8")
    old = registry_3_tenants()
    added = retire(path, old.canaries, retired_in="v1")
    assert len(added) == len(old.canaries)
    again = retire(path, old.canaries, retired_in="v1")
    assert again == []
    loaded = load_retired(path)
    assert all(r.retired_in == "v1" for r in loaded)
    assert {r.token for r in loaded} == {c.token for c in old.canaries}
    assert list(json.loads(path.read_text("utf-8"))[0]) == [
        "token",
        "tenant",
        "fact",
        "retired_in",
        "probe_question",
        "forbidden_answer",
    ]


def test_committed_retired_file_is_an_empty_list_in_v1() -> None:
    assert load_retired(REPO / "datasets" / "canaries" / "retired.json") == []


def test_malformed_retired_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "retired.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(DatasetError, match="retired"):
        load_retired(path)
