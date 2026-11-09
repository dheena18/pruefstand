"""``core.canary``: the folding mask shared by gate and report (T1.7b)."""

from pruefstand.core.canary import CANARY_MASK, CONFUSABLES, IGNORABLE, mask_canaries


def test_a_plain_token_is_masked() -> None:
    assert mask_canaries("x CANARY-VN-7f3a9c y") == f"x {CANARY_MASK} y"


def test_white_space_inside_the_hex_run_is_part_of_the_token() -> None:
    assert mask_canaries("CANARY VN 7f 3a 9c.") == f"{CANARY_MASK}."


def test_the_hex_run_stops_at_a_white_space_gap_after_six_digits() -> None:
    assert mask_canaries("CANARY-VN-7f3a9c Ende") == f"{CANARY_MASK} Ende"


def test_tables_hold_the_known_entries() -> None:
    assert IGNORABLE.match("\u200b") is not None
    assert CONFUSABLES[0x0430] == "a"


def test_text_without_a_token_is_unchanged() -> None:
    assert mask_canaries("Der Kanarienvogel singt.") == "Der Kanarienvogel singt."
