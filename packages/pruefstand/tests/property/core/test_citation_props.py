"""Property tests for the citation parser (T1.5a, S6)."""

from hypothesis import given
from hypothesis import strategies as st

from pruefstand.core.citations import Citation, extract_citations, normalise, parse_one

numbers = st.from_regex(r"[1-9][0-9]{0,3}[a-z]?", fullmatch=True)
sub = st.one_of(st.none(), st.from_regex(r"[1-9][0-9]?[a-z]?", fullmatch=True))
citations = st.builds(
    Citation,
    kind=st.sampled_from(["para", "art"]),
    number=numbers,
    absatz=sub,
    satz=sub,
    nummer=sub,
    lit=st.one_of(st.none(), st.from_regex(r"[a-z]", fullmatch=True)),
    law=st.sampled_from(["BGB", "HGB", "KSchG", "GG", "DSGVO", "KI-VO", "NIS2-RL", "DSA"]),
)


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
