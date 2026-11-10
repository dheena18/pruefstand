"""load_pins reads data/sources.yaml with the hardened loader (T2.5a)."""

from pathlib import Path

import pytest

from pruefstand.core.errors import ConfigError
from pruefstand.ingest.pins import load_pins

REPO = Path(__file__).resolve().parents[5]


def test_the_committed_sources_file_has_its_pins() -> None:
    pins = load_pins(REPO / "data" / "sources.yaml")
    assert pins["gii:kschg"] == "2026-10-31"
    assert len(pins) >= 50


def test_entries_without_a_pin_or_an_id_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "s.yaml"
    path.write_text(
        "sources:\n  - {id: a, pinned: '2026-01-01'}\n  - {id: b}\n  - {pinned: x}\n  - plain\n"
        "  - {id: c, revision: abc}\n",
        encoding="utf-8",
    )
    assert load_pins(path) == {"a": "2026-01-01", "c": "abc"}


@pytest.mark.parametrize(
    "text",
    [
        "sources:\n  - &a {id: a, pinned: x}\n  - *a\n",  # alias
        "sources: []\nsources: []\n",  # duplicate key
        "- not a mapping\n",
        "other: 1\n",  # no sources list
        "sources: [" + "[" * 40 + "]" * 40 + "]\n",  # nesting
    ],
)
def test_hostile_or_misshapen_files_are_config_errors(tmp_path: Path, text: str) -> None:
    path = tmp_path / "s.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_pins(path)


def test_a_symlinked_file_and_a_missing_file_are_config_errors(tmp_path: Path) -> None:
    real = tmp_path / "real.yaml"
    real.write_text("sources: []\n", encoding="utf-8")
    link = tmp_path / "link.yaml"
    link.symlink_to(real)
    with pytest.raises(ConfigError):
        load_pins(link)
    with pytest.raises(ConfigError):
        load_pins(tmp_path / "missing.yaml")
