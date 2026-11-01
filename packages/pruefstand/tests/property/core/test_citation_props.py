"""Property tests for the citation parser (T1.5a, S6)."""

import time

from hypothesis import given
from hypothesis import strategies as st

from pruefstand.core.citations import Citation, extract_citations, normalise, parse_one

numbers = st.from_regex(r"[1-9][0-9]{0,3}[a-z]?", fullmatch=True)
sub = st.one_of(st.none(), st.from_regex(r"[1-9][0-9]?[a-z]?", fullmatch=True))
_NATIONAL = ["BGB", "HGB", "KSchG", "GG"]
_EU = ["DSGVO", "KI-VO", "NIS2-RL", "DSA"]
_parts = {
    "number": numbers,
    "absatz": sub,
    "satz": sub,
    "nummer": sub,
    "lit": st.one_of(st.none(), st.from_regex(r"[a-z]", fullmatch=True)),
}
citations = st.builds(
    Citation, kind=st.just("para"), law=st.sampled_from(_NATIONAL), **_parts
) | st.builds(Citation, kind=st.just("art"), law=st.sampled_from(_NATIONAL + _EU), **_parts)


@given(st.text())
def test_never_raises_on_arbitrary_unicode(text: str) -> None:
    extract_citations(text)
    parse_one(text)


@given(st.text(alphabet="§Art.bs 0123456789()–,-fi.V.mSeciobGDGB ", max_size=80))
def test_never_raises_on_citation_like_noise(text: str) -> None:
    extract_citations(text)


@given(citations, st.sampled_from(["default", "full"]))
def test_normalise_is_idempotent(c: Citation, granularity: str) -> None:
    text = normalise(c, granularity)  # type: ignore[arg-type]  # str from sampled_from is a valid Literal
    parsed = parse_one(text)
    assert parsed is not None
    assert normalise(parsed, granularity) == text  # type: ignore[arg-type]  # same as above


@given(citations)
def test_full_roundtrip_preserves_the_model(c: Citation) -> None:
    assert parse_one(normalise(c, "full")) == c


_FRAGMENTS = [
    "s. ",
    "Sec. ",
    "Abs. ",
    "§ ",
    "Art. ",
    "i.V.m. ",
    "1 ",
    "und ",
    "lit. a ",
    "BGB ",
    "(2) ",
]


@given(st.lists(st.sampled_from(_FRAGMENTS), min_size=1, max_size=12))
def test_repeated_fragments_stay_fast(fragments: list[str]) -> None:
    text = "".join(fragments) * 1500
    start = time.perf_counter()
    extract_citations(text)
    assert time.perf_counter() - start < 5.0
