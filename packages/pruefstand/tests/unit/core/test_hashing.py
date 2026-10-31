import hashlib
import unicodedata
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from pruefstand.core.hashing import stable_hash


class Sample(BaseModel):
    name: str
    values: tuple[int, ...]


def test_exact_digest_of_canonical_json() -> None:
    expected = hashlib.sha256('[{"a":"ä","b":1}]'.encode()).hexdigest()[:16]
    assert stable_hash({"b": 1, "a": "ä"}) == expected


def test_variadic_is_not_concatenation() -> None:
    assert stable_hash("a", "b") != stable_hash("ab")


def test_tuple_equals_list() -> None:
    assert stable_hash(("a", 1)) == stable_hash(["a", 1])


def test_dict_key_order_irrelevant() -> None:
    assert stable_hash({"x": 1, "y": {"b": 2, "a": 3}}) == stable_hash(
        {"y": {"a": 3, "b": 2}, "x": 1}
    )


def test_list_order_matters() -> None:
    assert stable_hash([1, 2]) != stable_hash([2, 1])


def test_nfc_and_nfd_differ() -> None:
    nfc = unicodedata.normalize("NFC", "Kündigung")
    nfd = unicodedata.normalize("NFD", "Kündigung")
    assert nfc != nfd
    assert stable_hash(nfc) != stable_hash(nfd)


def test_model_equals_its_json_dump() -> None:
    model = Sample(name="Kündigung", values=(1, 2))
    assert stable_hash(model) == stable_hash(model.model_dump(mode="json"))


def test_bytes_are_stable_and_distinct_from_str() -> None:
    assert stable_hash(b"\x00") == stable_hash(b"\x00")
    assert stable_hash(b"\x00") != stable_hash("\x00")
    assert stable_hash(b"\x00") == stable_hash({"__bytes__": "00"})


def test_path_and_dates() -> None:
    assert stable_hash(Path("a/b")) == stable_hash("a/b")
    assert stable_hash(date(2026, 11, 2)) == stable_hash("2026-11-02")
    moment = datetime(2026, 11, 2, 3, 4, 5, tzinfo=UTC)
    assert stable_hash(moment) == stable_hash(moment.isoformat())


def test_scalars_and_none() -> None:
    scalars = (None, 0, False, "")
    assert len({stable_hash(x) for x in scalars}) == 4
    assert len(stable_hash(*(1.5, True, None))) == 16


def test_unsupported_type_raises() -> None:
    with pytest.raises(TypeError, match="object"):
        stable_hash(object())
    with pytest.raises(TypeError, match="set"):
        stable_hash({1, 2})


def test_non_string_mapping_key_raises() -> None:
    with pytest.raises(TypeError, match="key"):
        stable_hash({1: "a"})


def test_nan_is_rejected() -> None:
    with pytest.raises(ValueError, match="Out of range"):
        stable_hash(float("nan"))


def test_no_parts() -> None:
    assert stable_hash() == hashlib.sha256(b"[]").hexdigest()[:16]
