"""``scripts/live/record_target.py`` records what the target answers (replay reproduces it)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
import yaml
from live.record_target import main
from testsupport.pipeline_support import MINI_DATASET
from testsupport.target_cassette import CASSETTES, TargetCassette

URL = "http://rec.test"


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=URL, assert_all_called=False) as mock:
        yield mock


def _load(directory: Path, name: str) -> dict[str, object]:
    loaded = yaml.safe_load((directory / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_recording_a_replayed_target_reproduces_the_cassette(
    router: respx.MockRouter, tmp_path: Path
) -> None:
    cassette = TargetCassette("good")
    cassette.install(router)
    out = tmp_path / "good"
    code = main(["--url", URL, "--cases", str(MINI_DATASET / "smoke.jsonl"), "--out", str(out)])
    assert code == 0
    assert cassette.misses == []
    assert _load(out, "info.yaml")["response"] == _load(CASSETTES / "good", "info.yaml")["response"]
    assert _load(out, "query.yaml") == _load(CASSETTES / "good", "query.yaml")
    assert (out / "query.yaml").read_text(encoding="utf-8").startswith("# recorded ")


def test_the_header_carries_the_git_sha_the_target_reports(
    router: respx.MockRouter, tmp_path: Path
) -> None:
    cassette = TargetCassette("good")
    cassette.install(router)
    sha = cassette.info["git_sha"]
    out = tmp_path / "good"
    assert (
        main(["--url", URL, "--cases", str(MINI_DATASET / "smoke.jsonl"), "--out", str(out)]) == 0
    )
    for name in ("info.yaml", "query.yaml"):
        first = (out / name).read_text(encoding="utf-8").splitlines()[0]
        assert first.endswith(f"(git {sha})")


def test_an_unsafe_or_missing_git_sha_is_recorded_as_unknown(
    router: respx.MockRouter, tmp_path: Path
) -> None:
    cassette = TargetCassette("good", info_overrides={"git_sha": "a b\nc"})
    cassette.install(router)
    out = tmp_path / "odd"
    assert (
        main(["--url", URL, "--cases", str(MINI_DATASET / "smoke.jsonl"), "--out", str(out)]) == 0
    )
    assert (out / "info.yaml").read_text(encoding="utf-8").splitlines()[0].endswith("(git unknown)")


def test_a_failing_query_writes_nothing_and_exits_one(
    router: respx.MockRouter, tmp_path: Path
) -> None:
    router.get("/v1/info").respond(200, json={"app_version": "x"})
    router.post("/v1/query").respond(500, json={"detail": "down"})
    out = tmp_path / "bad"
    code = main(["--url", URL, "--cases", str(MINI_DATASET / "smoke.jsonl"), "--out", str(out)])
    assert code == 1
    assert not out.exists()
