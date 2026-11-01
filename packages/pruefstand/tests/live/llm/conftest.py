"""vcr settings for the cassette tests: replay only, no host/port in the match, no secrets."""

from pathlib import Path

import pytest

CASSETTES = Path(__file__).resolve().parents[2] / "cassettes" / "llm"


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, object]:
    return {
        "match_on": ["method", "path", "body"],
        "filter_headers": ["authorization", "api-key", "x-api-key"],
        "allow_playback_repeats": False,
    }


@pytest.fixture(scope="module")
def vcr_cassette_dir() -> str:
    return str(CASSETTES)
