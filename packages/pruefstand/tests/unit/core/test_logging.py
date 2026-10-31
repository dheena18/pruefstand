import json
import logging
from collections.abc import Iterator

import pytest

from pruefstand.core.logging import configure_logging, get_logger

TOKENS = ["sk-abcdefgh12", "hf_abcdefgh12", "ghp_abcdefgh12", "ghs_abcdefgh12"]


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    yield
    configure_logging(json=False, level="INFO")


def lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [line for line in capsys.readouterr().err.splitlines() if line.strip()]


def test_key_redaction_keeps_other_fields(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(json=True, level="INFO")
    get_logger("t").info("x", api_key="sk-123", tenant="kanzlei_mueller")
    (out,) = lines(capsys)
    data = json.loads(out)
    assert data["api_key"] == "[REDACTED]"
    assert data["tenant"] == "kanzlei_mueller"
    assert "sk-123" not in out
    assert data["event"] == "x"


@pytest.mark.parametrize("name", ["Authorization", "client_SECRET", "password", "hf_token", "KEY"])
def test_key_pattern_is_case_insensitive(name: str, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(json=True, level="INFO")
    get_logger("t").info("x", **{name: "plain-value"})
    (out,) = lines(capsys)
    assert json.loads(out)[name] == "[REDACTED]"
    assert "plain-value" not in out


def test_nested_values_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(json=True, level="INFO")
    get_logger("t").info(
        "x", headers={"authorization": "Bearer abc", "ok": ["fine", "ghp_abcdefgh12"]}
    )
    (out,) = lines(capsys)
    assert "Bearer abc" not in out
    assert "ghp_abcdefgh12" not in out
    assert "fine" in out


@pytest.mark.parametrize("token", TOKENS)
def test_token_in_free_text_is_redacted(token: str, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(json=True, level="INFO")
    get_logger("t").error(f"call failed with token {token} x")
    (out,) = lines(capsys)
    assert token not in out
    assert "[REDACTED]" in out
    assert "call failed with token" in out


@pytest.mark.parametrize("token", TOKENS)
def test_token_in_exception_is_redacted(token: str, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(json=True, level="INFO")
    log = get_logger("t")
    try:
        raise RuntimeError(f"upstream said {token}")  # noqa: TRY301
    except RuntimeError:
        log.exception("failed")
    err = RuntimeError(f"again {token}")
    log.error("failed", error=err)
    out = "\n".join(lines(capsys))
    assert token not in out
    assert "RuntimeError" in out


def test_plain_text_mode_also_redacts(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(json=False, level="INFO")
    get_logger("t").info("hello ghp_abcdefgh12", api_key="abc")
    out = capsys.readouterr().err
    assert "ghp_abcdefgh12" not in out
    assert "abc" not in out
    assert "hello" in out


def test_level_filters(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(json=True, level="WARNING")
    log = get_logger("t")
    log.info("quiet")
    log.warning("loud")
    out = lines(capsys)
    assert len(out) == 1
    assert json.loads(out[0])["event"] == "loud"


def test_reconfigure_does_not_duplicate_handlers(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(json=True, level="INFO")
    configure_logging(json=True, level="INFO")
    get_logger("t").info("once")
    assert len(lines(capsys)) == 1


def test_invalid_level_is_an_error() -> None:
    with pytest.raises(ValueError, match="level"):
        configure_logging(json=True, level="LOUD")


def test_stdlib_loggers_are_redacted_too(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(json=True, level="INFO")
    logging.getLogger("third.party").warning("saw ghp_abcdefgh12")
    out = "\n".join(lines(capsys))
    assert "ghp_abcdefgh12" not in out
    assert "saw" in out


def test_get_logger_before_configure_still_redacts(capsys: pytest.CaptureFixture[str]) -> None:
    get_logger("early").info("x", password="hunter2")
    assert "hunter2" not in capsys.readouterr().err
