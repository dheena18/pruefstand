"""T8.4: the public-mode error body."""

import json

import pytest

from rag_demo.public.errors import MESSAGES, STATUS, Rejection, error_body


@pytest.mark.parametrize("code", sorted(STATUS))
def test_every_error_body_has_exactly_code_message_and_retry_after(code: str) -> None:
    rejection = Rejection(code, 3)  # type: ignore[arg-type]  # parametrised over the codes
    body = rejection.body()
    assert set(body) == {"code", "message", "retry_after_s"}
    assert body["code"] == code
    assert body["retry_after_s"] == 3
    text = json.dumps(body)
    assert "Traceback" not in text
    assert 'File "' not in text


def test_codes_statuses_and_messages_cover_the_same_set() -> None:
    assert set(STATUS) == set(MESSAGES)
    assert STATUS == {
        "rate_limited": 429,
        "daily_limit": 429,
        "busy": 429,
        "budget_exhausted": 503,
        "demo_disabled": 503,
        "invalid_request": 422,
        "body_too_large": 413,
        "timeout": 504,
    }


def test_retry_after_header_only_when_a_retry_makes_sense() -> None:
    assert Rejection("busy", 5).headers() == {"Retry-After": "5"}
    assert Rejection("demo_disabled").headers() == {}
    assert error_body("demo_disabled")["retry_after_s"] is None
