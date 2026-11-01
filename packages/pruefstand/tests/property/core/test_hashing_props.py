import re

from hypothesis import given
from hypothesis import strategies as st

from pruefstand.core.hashing import stable_hash

scalars = st.none() | st.booleans() | st.integers() | st.text()
values = st.recursive(
    scalars,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(), inner, max_size=4),
    max_leaves=12,
)
shuffled_mappings = st.dictionaries(st.text(), values, max_size=6).flatmap(
    lambda m: st.tuples(st.just(m), st.permutations(list(m.items())))
)


@given(st.lists(values, max_size=4))
def test_length_hex_and_determinism(parts: list[object]) -> None:
    digest = stable_hash(*parts)
    assert re.fullmatch(r"[0-9a-f]{16}", digest)
    assert stable_hash(*parts) == digest


@given(shuffled_mappings)
def test_dict_order_invariant(case: tuple[dict[str, object], list[tuple[str, object]]]) -> None:
    mapping, items = case
    assert stable_hash(dict(items)) == stable_hash(mapping)
