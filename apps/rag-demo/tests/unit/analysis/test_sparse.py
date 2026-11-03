"""SparseEncoder: xxhash64 vocabulary and BM25 term weights (T3.3; T1.13 cases moved)."""

import subprocess
import sys

import xxhash

from rag_demo.analysis.sparse import SparseEncoder, token_index

E = SparseEncoder()


def test_empty_token_list_gives_an_empty_vector() -> None:
    vec = E.encode([])
    assert vec.indices == []
    assert vec.values == []


def test_repeated_token_is_one_index_with_saturating_weight() -> None:
    once = E.encode(["frist"]).values[0]
    twice = E.encode(["frist", "frist"]).values[0]
    ten = E.encode(["frist"] * 10).values[0]
    assert once < twice < ten < (1.2 + 1)  # BM25 saturates below k1 + 1
    assert ten < 10 * once
    assert len(E.encode(["frist", "frist"]).indices) == 1


def test_indices_are_sorted_unique_and_in_range() -> None:
    vec = E.encode(["kuendigung", "frist", "frist", "arbeitnehmer"])
    assert vec.indices == sorted(set(vec.indices))
    assert all(0 <= i < 2**31 for i in vec.indices)
    assert len(vec.indices) == len(vec.values) == 3


def test_token_id_is_xxhash64_mod_2_pow_31() -> None:
    expected = xxhash.xxh64_intdigest(b"kuendigung") % 2**31
    assert token_index("kuendigung", E.dim) == expected
    assert E.dim == 2**31


def test_query_vector_has_unit_weights() -> None:
    vec = E.encode_query(["frist", "frist", "woche"])
    assert vec.values == [1.0, 1.0]


def test_index_is_stable_across_processes() -> None:
    code = (
        "from rag_demo.analysis.sparse import SparseEncoder as S;"
        "print(S().encode(['kuendigung']).indices)"
    )
    runs = {
        subprocess.run(  # noqa: S603
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": ""},
        ).stdout
        for seed in ("1", "2")
    }
    assert len(runs) == 1
    assert runs == {f"{E.encode(['kuendigung']).indices}\n"}
