"""Tests for data/download.py (T2.1): sources.yaml, checksums, licences, idempotence. No network."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import data_fetch
import data_hf
import httpx
import pytest
import respx
import yaml
from data_sources import ChecksumError, LicenseMismatch, SourcesError, load_sources
from download import main
from huggingface_hub.errors import HfHubHTTPError

REPO = Path(__file__).resolve().parents[2]
SOURCES = REPO / "data" / "sources.yaml"
ABC = b"abc"
ABC_SHA = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
HEX64 = set("0123456789abcdef")
GII_URL = "https://www.gesetze-im-internet.de/kschg/xml.zip"
CELLAR_URL = "https://publications.europa.eu/resource/celex/32016R0679"

CELEX = [
    "32016R0679", "32024R1689", "32022L2555", "32022R2065", "32022R1925", "32023R2854",
    "32022R0868", "32002L0058", "32024R2847", "32022R2554", "32014R0910", "32019L0944",
    "32019R0943", "32023L1791", "32011R1227", "32019L1937", "32011L0083", "32024L2853",
    "32003L0088", "32019L1152",
]  # fmt: skip
GII = [
    "BGB", "EGBGB", "HGB", "BDSG", "KSchG", "ArbZG", "ArbSchG", "UrhG", "VVG", "EnWG", "EnSiG",
    "BSIG", "TzBfG", "BUrlG", "EntgFG", "MuSchG", "AGG", "BetrVG", "GewO", "NachwG", "ArbGG",
    "SGB IV", "ProdHaftG", "UWG", "TDDDG", "GmbHG", "AktG", "InsO", "KWG", "VAG",
]  # fmt: skip
HF_IDS = {
    "oldp_decisions", "oldp_laws", "oldp_citation_graph", "germanquad", "germandpr",
    "germanrag", "prompt_injections",
}  # fmt: skip


def _kinds(kind: str) -> list[Any]:
    return [s for s in load_sources(SOURCES) if s.kind == kind]


def test_sources_yaml_counts_and_ids() -> None:
    assert len(_kinds("gii")) == 30
    assert len(_kinds("eurlex")) == 20
    assert len(_kinds("hf")) == 7
    assert len(_kinds("github")) == 1
    assert sorted(s.celex for s in _kinds("eurlex")) == sorted(CELEX)
    assert sorted(s.abbrev for s in _kinds("gii")) == sorted(GII)
    assert {s.id for s in _kinds("hf")} == HF_IDS
    assert {s.id for s in _kinds("gii")} == {"gii:" + a.lower().replace(" ", "") for a in GII}
    memerag = _kinds("github")[0]
    assert memerag.id == "memerag"
    assert memerag.redistribute is False
    assert memerag.license_config == "download_only"


def test_hf_entries_have_40_hex_revisions() -> None:
    for s in _kinds("hf"):
        assert s.revision is not None
        assert len(s.revision) == 40
        assert set(s.revision) <= HEX64
        assert s.revision != "main"
    text = SOURCES.read_text(encoding="utf-8")
    assert text.count("revision:") == 7
    assert "revision: main" not in text


def test_every_file_entry_has_64_hex_sha() -> None:
    for s in load_sources(SOURCES):
        assert s.files, s.id
        for name, sha in s.files.items():
            assert sha is not None, f"{s.id}/{name}"
            assert len(sha) == 64, f"{s.id}/{name}"
            assert set(sha) <= HEX64, f"{s.id}/{name}"


def _write_sources(tmp_path: Path, entries: list[dict[str, Any]]) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "sources": entries}), encoding="utf-8")
    return path


def _gii(sha: str | None = ABC_SHA) -> dict[str, Any]:
    return {
        "id": "gii:kschg", "kind": "gii", "abbrev": "KSchG", "slug": "kschg",
        "pinned": "2026-10-31", "license": "official-work", "license_config": "laws_eurlex",
        "redistribute": True, "attribution": "BMJ", "files": {"xml.zip": sha},
    }  # fmt: skip


def _hf(
    license_: str = "cc-by-4.0", config: str | None = None, sha: str | None = ABC_SHA
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "germanquad", "kind": "hf", "repo_id": "deepset/germanquad",
        "revision": "a" * 40, "license": license_, "license_config": "germanquad_derived",
        "redistribute": True, "attribution": "deepset",
        "files": {"plain_text/test/0000.parquet": sha},
    }  # fmt: skip
    if config:
        entry["config"] = config
    return entry


def _args(tmp_path: Path, src: Path, *extra: str) -> list[str]:
    return ["--sources", str(src), "--raw", str(tmp_path / "raw"), "--no-sleep", *extra]


def test_checksum_accepted_and_manifest_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _write_sources(tmp_path, [_gii()])
    with respx.mock:
        route = respx.get(GII_URL).respond(content=ABC)
        assert main(_args(tmp_path, src)) == 0
    assert route.call_count == 1
    assert (tmp_path / "raw/gii/kschg/xml.zip").read_bytes() == ABC
    manifest = json.loads((tmp_path / "raw/MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest == {"gii:kschg": {"pin": "2026-10-31", "files": {"xml.zip": ABC_SHA}}}
    assert "verified 1 files, 0 mismatches, 0 license mismatches" in capsys.readouterr().out


def test_wrong_checksum_names_source_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = _write_sources(tmp_path, [_gii(sha="0" * 64)])
    with respx.mock:
        respx.get(GII_URL).respond(content=ABC)
        assert main(_args(tmp_path, src)) == 1
    err = capsys.readouterr().err
    assert "gii:kschg" in err
    assert "0" * 64 in err
    assert ABC_SHA in err
    assert not (tmp_path / "raw/gii/kschg/xml.zip").exists()


def test_checksum_error_type(tmp_path: Path) -> None:
    source = load_sources(_write_sources(tmp_path, [_gii(sha="0" * 64)]))[0]
    with respx.mock, httpx.Client() as client:
        respx.get(GII_URL).respond(content=ABC)
        with pytest.raises(ChecksumError, match="gii:kschg"):
            data_fetch.sync_source(source, tmp_path / "raw", client=client, sleep=lambda _s: None)


def test_second_run_downloads_nothing(tmp_path: Path) -> None:
    src = _write_sources(tmp_path, [_gii()])
    with respx.mock:
        route = respx.get(GII_URL).respond(content=ABC)
        assert main(_args(tmp_path, src)) == 0
        assert main(_args(tmp_path, src)) == 0
    assert route.call_count == 1


def test_retries_transient_errors_then_succeeds(tmp_path: Path) -> None:
    src = _write_sources(tmp_path, [_gii()])
    with respx.mock:
        route = respx.get(GII_URL)
        route.side_effect = [
            httpx.Response(503),
            httpx.ConnectError("boom"),
            httpx.Response(200, content=ABC),
        ]
        assert main(_args(tmp_path, src)) == 0
    assert route.call_count == 3


def test_resumes_partial_download(tmp_path: Path) -> None:
    src = _write_sources(tmp_path, [_gii()])
    part = tmp_path / "raw/gii/kschg/xml.zip.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"ab")
    with respx.mock:
        route = respx.get(GII_URL).respond(206, content=b"c")
        assert main(_args(tmp_path, src)) == 0
    assert route.calls[0].request.headers["range"] == "bytes=2-"
    assert (tmp_path / "raw/gii/kschg/xml.zip").read_bytes() == ABC


def test_user_agent_is_set(tmp_path: Path) -> None:
    src = _write_sources(tmp_path, [_gii()])
    with respx.mock:
        route = respx.get(GII_URL).respond(content=ABC)
        main(_args(tmp_path, src))
    assert route.calls[0].request.headers["user-agent"].startswith("pruefstand-data/")


def test_waf_challenge_is_reported_not_bypassed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entry = {
        "id": "eurlex:32016R0679", "kind": "eurlex", "celex": "32016R0679",
        "pinned": "2026-10-31", "license": "eurlex-notice", "license_config": "laws_eurlex",
        "redistribute": True, "attribution": "EU", "files": {"de.html": None},
    }  # fmt: skip
    src = _write_sources(tmp_path, [entry])
    url = CELLAR_URL
    with respx.mock:
        respx.get(url).respond(202, headers={"x-amzn-waf-action": "challenge"})
        assert main(_args(tmp_path, src)) == 1
    assert "challenge" in capsys.readouterr().err


def test_verify_only_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = _write_sources(tmp_path, [_gii()])
    assert main(_args(tmp_path, src, "--verify-only")) == 1
    assert "missing: gii/kschg/xml.zip" in capsys.readouterr().out


def test_verify_only_detects_corruption(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = _write_sources(tmp_path, [_gii()])
    target = tmp_path / "raw/gii/kschg/xml.zip"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"abd")
    assert main(_args(tmp_path, src, "--verify-only")) == 1
    out = capsys.readouterr()
    assert "gii:kschg" in out.out + out.err
    target.write_bytes(ABC)
    assert main(_args(tmp_path, src, "--verify-only")) == 0


def test_only_selects_one_source(tmp_path: Path) -> None:
    other = {**_gii(), "id": "gii:bgb", "abbrev": "BGB", "slug": "bgb"}
    src = _write_sources(tmp_path, [_gii(), other])
    with respx.mock:
        route = respx.get(GII_URL).respond(content=ABC)
        assert main(_args(tmp_path, src, "--only", "gii:kschg")) == 0
    assert route.call_count == 1
    assert not (tmp_path / "raw/gii/bgb").exists()


def _info(license_: str | None, configs: list[str] | None = None) -> SimpleNamespace:
    card = SimpleNamespace(
        license=license_, configs=[{"config_name": c} for c in configs] if configs else None
    )
    return SimpleNamespace(card_data=card, sha="a" * 40)


def _fake_snapshot(calls: list[str]) -> Any:
    def snapshot_download(**kwargs: Any) -> str:
        calls.append(kwargs["repo_id"])
        for pattern in kwargs["allow_patterns"]:
            target = Path(kwargs["local_dir"]) / pattern
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(ABC)
        return str(kwargs["local_dir"])

    return snapshot_download


def test_hf_download_checks_license_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(data_hf, "snapshot_download", _fake_snapshot(calls))
    monkeypatch.setattr(data_hf, "dataset_info", lambda *_a, **_k: _info("cc-by-4.0"))
    src = _write_sources(tmp_path, [_hf()])
    assert main(_args(tmp_path, src)) == 0
    assert main(_args(tmp_path, src)) == 0
    assert calls == ["deepset/germanquad"]
    assert (tmp_path / "raw/hf/germanquad/plain_text/test/0000.parquet").read_bytes() == ABC


def test_license_mismatch_exit_3_names_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(data_hf, "snapshot_download", _fake_snapshot(calls))
    monkeypatch.setattr(data_hf, "dataset_info", lambda *_a, **_k: _info("cc-by-4.0"))
    src = _write_sources(tmp_path, [_hf(license_="cc-by-sa-4.0")])
    assert main(_args(tmp_path, src)) == 3
    err = capsys.readouterr().err
    assert "cc-by-4.0" in err
    assert "cc-by-sa-4.0" in err
    assert "germanquad" in err
    assert calls == []


def test_license_mismatch_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_hf, "dataset_info", lambda *_a, **_k: _info("cc-by-4.0"))
    good = load_sources(_write_sources(tmp_path, [_hf()]))[0]
    data_hf.check_hf_license(good)
    (tmp_path / "bad").mkdir()
    bad = load_sources(_write_sources(tmp_path / "bad", [_hf(license_="cc-by-sa-4.0")]))[0]
    with pytest.raises(LicenseMismatch, match=r"cc-by-sa-4\.0"):
        data_hf.check_hf_license(bad)


def test_hf_missing_config_exit_2_lists_configs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(data_hf, "snapshot_download", _fake_snapshot([]))
    info = _info("cc-by-4.0", ["dump-20221018-1k", "dump-20260520-10k"])
    monkeypatch.setattr(data_hf, "dataset_info", lambda *_a, **_k: info)
    src = _write_sources(tmp_path, [_hf(config="dump-20260520-1k")])
    assert main(_args(tmp_path, src)) == 2
    err = capsys.readouterr().err
    assert "dump-20221018-1k" in err
    assert "dump-20260520-10k" in err


def test_github_license_detected_from_file(tmp_path: Path) -> None:
    licence = b"Attribution-NonCommercial 4.0 International\n" + b"=" * 20
    entry = {
        "id": "memerag", "kind": "github", "repo": "amazon-science/MEMERAG", "commit": "b" * 40,
        "license": "cc-by-nc-4.0", "license_config": "download_only", "redistribute": False,
        "attribution": "Amazon", "files": {"LICENSE": hashlib.sha256(licence).hexdigest()},
    }  # fmt: skip
    src = _write_sources(tmp_path, [entry])
    url = f"https://raw.githubusercontent.com/amazon-science/MEMERAG/{'b' * 40}/LICENSE"
    with respx.mock:
        respx.get(url).respond(content=licence)
        assert main(_args(tmp_path, src)) == 0
        assert (tmp_path / "raw/github/memerag/LICENSE").read_bytes() == licence
        entry["license"] = "cc-by-4.0"
        src = _write_sources(tmp_path, [entry])
        assert main(_args(tmp_path, src)) == 3


def test_update_pins_rewrites_sha_and_prints_diff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CI", raising=False)
    src = _write_sources(tmp_path, [_gii(sha=None)])
    with respx.mock:
        respx.get(GII_URL).respond(content=ABC)
        assert main(_args(tmp_path, src, "--update-pins")) == 0
    assert load_sources(src)[0].files == {"xml.zip": ABC_SHA}
    assert ABC_SHA in capsys.readouterr().out


def test_update_pins_refuses_in_ci(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    src = _write_sources(tmp_path, [_gii()])
    assert main(_args(tmp_path, src, "--update-pins")) == 4


def test_gated_dataset_is_a_fetch_error_without_token_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def gated(**_kwargs: Any) -> str:
        msg = "401 gated"
        response = httpx.Response(401, request=httpx.Request("GET", "https://hf.co"))
        raise HfHubHTTPError(msg, response=response)

    monkeypatch.setattr(data_hf, "snapshot_download", gated)
    monkeypatch.setattr(data_hf, "dataset_info", lambda *_a, **_k: _info("cc-by-4.0"))
    src = _write_sources(tmp_path, [_hf()])
    assert main(_args(tmp_path, src)) == 1
    assert "HF_TOKEN" in capsys.readouterr().err


def test_unknown_only_id_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _write_sources(tmp_path, [_gii()])
    assert main(_args(tmp_path, src, "--only", "gii:nope")) == 4
    assert "gii:nope" in capsys.readouterr().err


def test_file_names_cannot_escape_the_source_dir(tmp_path: Path) -> None:
    entry = _gii()
    entry["files"] = {"../evil.zip": ABC_SHA}
    with pytest.raises(SourcesError, match="relative"):
        load_sources(_write_sources(tmp_path, [entry]))


def test_eurlex_uses_cellar_with_language_negotiation(tmp_path: Path) -> None:
    entry = {
        "id": "eurlex:32016R0679", "kind": "eurlex", "celex": "32016R0679",
        "pinned": "2026-10-31", "license": "eurlex-legal-notice", "license_config": "laws_eurlex",
        "redistribute": True, "attribution": "EU",
        "files": {"de.html": ABC_SHA, "en.html": ABC_SHA},
    }  # fmt: skip
    src = _write_sources(tmp_path, [entry])
    with respx.mock:
        route = respx.get(CELLAR_URL).respond(content=ABC)
        assert main(_args(tmp_path, src)) == 0
    langs = sorted(c.request.headers["accept-language"] for c in route.calls)
    assert langs == ["deu", "eng"]
    assert (tmp_path / "raw/eurlex/32016R0679/de.html").read_bytes() == ABC


def test_manifest_shape_of_committed_sources() -> None:
    sources = load_sources(SOURCES)
    assert len(sources) == 58


def test_card_license_override_accepts_exactly_the_documented_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(data_hf, "dataset_info", lambda *_a, **_k: _info(None))
    plain = load_sources(_write_sources(tmp_path, [_hf(license_="odbl")]))[0]
    with pytest.raises(LicenseMismatch, match="none"):
        data_hf.check_hf_license(plain)
    entry = {**_hf(license_="odbl"), "card_license": "none"}
    (tmp_path / "o").mkdir()
    data_hf.check_hf_license(load_sources(_write_sources(tmp_path / "o", [entry]))[0])
    monkeypatch.setattr(data_hf, "dataset_info", lambda *_a, **_k: _info("cc-by-4.0"))
    with pytest.raises(LicenseMismatch, match="cc-by-4"):
        data_hf.check_hf_license(load_sources(_write_sources(tmp_path / "o", [entry]))[0])


def test_committed_overrides_are_exactly_two() -> None:
    overridden = {s.id: s.card_license for s in load_sources(SOURCES) if s.card_license}
    assert overridden == {"oldp_decisions": "none", "germanrag": "cc-by-4.0"}


def _two(first: str, second: str, tmp_path: Path) -> Path:
    a = {**_hf(license_=first), "id": "a"}
    b = {**_hf(license_=second), "id": "b"}
    return _write_sources(tmp_path, [a, b])


@pytest.mark.parametrize(
    ("first", "second"),
    [("cc-by-4.0", "cc-by-sa-4.0"), ("odbl", "cc-by-4.0"), ("odbl", "cc-by-sa-4.0")],
)
def test_config_never_mixes_share_alike_with_other_licences(
    tmp_path: Path, first: str, second: str
) -> None:
    with pytest.raises(SourcesError, match="germanquad_derived"):
        load_sources(_two(first, second, tmp_path))


def test_config_with_one_licence_is_fine(tmp_path: Path) -> None:
    assert len(load_sources(_two("cc-by-sa-4.0", "cc-by-sa-4.0", tmp_path))) == 2


def test_germanrag_is_share_alike_in_its_own_config() -> None:
    by_id = {s.id: s for s in load_sources(SOURCES)}
    rag = by_id["germanrag"]
    assert rag.license == "cc-by-sa-4.0"
    assert rag.license_config == "germanrag_derived"
    others = [s for s in by_id.values() if s.license_config == "germanrag_derived"]
    assert others == [rag]
    assert by_id["germanquad"].license_config != rag.license_config
