"""T1.10a leftovers: the corpus-mismatch message is bounded; the calibration-file branch."""

from pathlib import Path

import pytest
import respx
from contract.adapter_contract import load_openapi_example
from testsupport.pipeline_support import CORPUS_VERSION, case_rows, synthetic_config, write_dataset
from testsupport.run_builders import make_cases

from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError, CorpusMismatch
from pruefstand.pipeline import fingerprints
from pruefstand.pipeline.run import run_eval


async def test_a_long_target_corpus_version_is_truncated_in_the_mismatch_message(
    tmp_path: Path, router: respx.MockRouter
) -> None:
    dataset = write_dataset(tmp_path / "ds", {"smoke": case_rows(make_cases(2, split="smoke"))})
    hostile = "x" * 5000 + "\nSECRET-TAIL"
    info = {**load_openapi_example("info.json"), "corpus_version": hostile}
    router.get("/v1/info").respond(200, json=info)
    cfg = synthetic_config(dataset, (Split.SMOKE,))
    with pytest.raises(CorpusMismatch) as caught:
        await run_eval(cfg, tier="pr", out=tmp_path / "runs")
    text = str(caught.value)
    assert "SECRET-TAIL" not in text
    assert len(text) < 1000
    assert CORPUS_VERSION in text


class _Files:
    """A stand-in for ``importlib.resources`` whose package root is a temporary directory."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def files(self, package: str) -> Path:
        assert package == "pruefstand.judges"
        return self._root


def with_calibration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str | None) -> None:
    (tmp_path / "data").mkdir()
    if text is not None:
        (tmp_path / "data" / "calibration_status.yaml").write_text(text, encoding="utf-8")
    monkeypatch.setattr(fingerprints, "resources", _Files(tmp_path))


def test_no_calibration_file_means_epoch_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with_calibration(monkeypatch, tmp_path, None)
    assert fingerprints.calibration_epoch() == 0


def test_the_epoch_is_read_from_the_calibration_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with_calibration(monkeypatch, tmp_path, "epoch: 3\njudges: {}\n")
    assert fingerprints.calibration_epoch() == 3


@pytest.mark.parametrize(
    "text",
    [
        "epoch: -1",
        "epoch: true",
        "epoch: 1.5",
        "epoch: 'x'",
        "judges: {}",
        "- a\n- b",
        ": : :\n\t[",
        "epoch: 1\n" + "#" * 100_001,
    ],
)
def test_a_calibration_file_without_a_non_negative_integer_epoch_is_a_config_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str
) -> None:
    with_calibration(monkeypatch, tmp_path, text)
    with pytest.raises(ConfigError, match="epoch"):
        fingerprints.calibration_epoch()
