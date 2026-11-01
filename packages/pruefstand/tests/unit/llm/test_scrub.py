"""Cassette scrubbing: an allow-list in the vcr hooks, one secret scanner, recording refuses."""

import asyncio
import json
from pathlib import Path

import pytest
import vcr  # type: ignore[import-untyped]  # vcrpy ships no stubs
import yaml
from testsupport.llm_scenarios import BACKEND_CASSETTE_DIR, CASSETTE_DIR, echo_request
from testsupport.loopback import serve
from testsupport.vcr_scrub import (
    REQUEST_HEADERS,
    RESPONSE_HEADERS,
    VCR_CONFIG,
    scrub_request,
)
from vcr.request import Request  # type: ignore[import-untyped]

from pruefstand.core.errors import LLMError
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.scrub import assert_no_secrets

LOOP_MODEL = "openai_compatible_local/loop"
GHP = "ghp_abcdefghijklmnop1234567890"
HOOKS = {k: v for k, v in VCR_CONFIG.items() if k.startswith("before_")}


@pytest.mark.parametrize(
    "text",
    [
        "sk-abcdefgh12345",
        "token ghp_abc",
        "gho_x ghu_x ghs_x ghr_x",
        "github_pat_11AAAA",
        "hf_abcdefgh1234",
        "Authorization: Bearer abcdefgh12345",
        "eyJhbGciOiJIUzI1NiJ9",
    ],
)
def test_secret_shapes_are_refused(text: str) -> None:
    with pytest.raises(LLMError, match="secret"):
        assert_no_secrets(text)


@pytest.mark.parametrize(
    "text",
    ["Die Kündigung muss schriftlich erfolgen.", "chatcmpl-HSVqZ9JJ", "hf_ short", "Bearer x"],
)
def test_ordinary_text_passes(text: str) -> None:
    assert_no_secrets(text)


def test_the_message_never_repeats_the_secret() -> None:
    with pytest.raises(LLMError) as info:
        assert_no_secrets(f"x {GHP} y")
    assert GHP not in str(info.value)


def _record_with_vcr(tmp_path: Path, base: str) -> str:
    backend = LiteLLMBackend(LOOP_MODEL, api_base=base, api_key_env=None, timeout_s=10)
    req = echo_request().model_copy(update={"model": LOOP_MODEL})
    path = tmp_path / "c.yaml"
    with vcr.VCR(record_mode="all", **HOOKS).use_cassette(str(path)):
        asyncio.run(backend.acomplete(req))
    return path.read_text("utf-8")


def test_vcr_hooks_keep_only_the_allow_listed_headers(tmp_path: Path) -> None:
    headers = {
        "Set-Cookie": "session=SECRETCOOKIE123",
        "X-Request-Id": "req-1",
        "X-GitHub-Request-Id": "gh-1",
        "X-Echo": f"Bearer {GHP}",
    }
    with serve(headers=headers) as base:
        text = _record_with_vcr(tmp_path, base)
    for leaked in (
        "SECRETCOOKIE123",
        "req-1",
        "gh-1",
        "ghp_",
        "Bearer",
        "x-stainless",
        "user-agent",
    ):
        assert leaked.lower() not in text.lower()
    data = yaml.safe_load(text)
    for item in data["interactions"]:
        assert {k.lower() for k in item["request"]["headers"]} <= REQUEST_HEADERS
        assert {k.lower() for k in item["response"]["headers"]} <= RESPONSE_HEADERS


def test_vcr_refuses_a_secret_in_the_response_body(tmp_path: Path) -> None:
    with serve(content=f"mein Token ist {GHP}") as base, pytest.raises(LLMError):
        _record_with_vcr(tmp_path, base)
    assert not (tmp_path / "c.yaml").exists() or GHP not in (tmp_path / "c.yaml").read_text("utf-8")


async def test_backend_cassette_recording_refuses_a_secret(tmp_path: Path) -> None:
    with serve(content=f"mein Token ist {GHP}") as base:
        real = LiteLLMBackend(LOOP_MODEL, api_base=base, api_key_env=None, timeout_s=10)
        recording = CassetteRecorder(tmp_path, "record").wrap(real)
        req = echo_request().model_copy(update={"model": LOOP_MODEL})
        with pytest.raises(LLMError, match="secret"):
            await recording.acomplete(req)
    assert list(tmp_path.iterdir()) == []  # noqa: ASYNC240


def test_every_committed_vcr_cassette_is_scrubbed() -> None:
    files = sorted(CASSETTE_DIR.glob("*.yaml"))
    assert len(files) >= 4
    for path in files:
        text = path.read_text("utf-8")
        assert_no_secrets(text)
        for item in yaml.safe_load(text)["interactions"]:
            assert {k.lower() for k in item["request"]["headers"]} <= REQUEST_HEADERS, path.name
            assert {k.lower() for k in item["response"]["headers"]} <= RESPONSE_HEADERS, path.name


def test_every_committed_backend_cassette_is_scrubbed() -> None:
    files = sorted(BACKEND_CASSETTE_DIR.glob("*.json"))
    assert len(files) >= 2
    for path in files:
        assert_no_secrets(path.read_text("utf-8"))
        assert set(json.loads(path.read_text("utf-8"))) == {
            "recorded_at", "model_id", "model_version", "request", "response",
        }  # fmt: skip


@pytest.mark.parametrize(
    "text",
    [
        '{"h": "Bearer\\tabcdefgh12345"}',
        "BEARER abcdefgh12345",
        "GHP_abcdefghijkl",
        "?token=Bearer%20abcdefgh12345",
        "AKIA" + "ABCDEFGHIJKLMNOP",
        "xoxb-1234-abcd",
        "glpat-abcdefgh1234",
        "AIzaSyA-abcdefghijklmnopqrstuvwxyz123",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIE",
        "password=hunter2hunter2",
        '{"cfg": "secret=abcd1234"}',
        '{"a": ["x", {"k": "ghp_abcdefghijklmnop"}]}',
    ],
)
def test_json_encoded_encoded_and_other_shapes_are_refused(text: str) -> None:
    with pytest.raises(LLMError, match="secret"):
        assert_no_secrets(text)


@pytest.mark.parametrize(
    "text",
    [
        "Risk-Management und Desk-Recherche",
        "Task-Force-Berichte",
        "Bank-Verbindung hf_ x",
        "Passwort ist geheim",
    ],
)
def test_benign_words_with_secret_looking_endings_pass(text: str) -> None:
    assert_no_secrets(text)


def test_request_uri_and_body_are_scanned_by_the_hook() -> None:
    with pytest.raises(LLMError, match="secret"):
        scrub_request(Request("GET", "http://h/v1?api=ghp_abcdefghijklmnop", None, {}))
    with pytest.raises(LLMError, match="secret"):
        scrub_request(Request("POST", "http://h/v1", b'{"k": "Bearer abcdefgh12345"}', {}))
    ok = scrub_request(Request("POST", "http://h/v1", b"{}", {"X-A": "b", "Content-Type": "c"}))
    assert dict(ok.headers) == {"Content-Type": "c"}


def test_repeated_url_encoding_does_not_hide_a_secret() -> None:
    once = "Bearer abcdefgh12345".replace(" ", "%20")
    twice = once.replace("%", "%25")
    thrice = twice.replace("%", "%25")
    for text in (once, twice, thrice):
        with pytest.raises(LLMError, match="secret"):
            assert_no_secrets(text)
