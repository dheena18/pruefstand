import pytest
from pydantic import ValidationError

from pruefstand.core.errors import LLMError, PolicyViolation, PruefstandError
from pruefstand.core.models.llm import LLMRequest, LLMResponse, LLMRole, Message
from pruefstand.core.models.target import Usage


def _request(**extra: object) -> LLMRequest:
    return LLMRequest(
        role=LLMRole.JUDGE,
        model="github/openai/gpt-4o-mini",
        messages=(Message(role="user", content="Hallo"),),
        prompt_id="echo",
        prompt_version="v1",
        **extra,  # type: ignore[arg-type]  # test passes optional fields by keyword
    )


def test_request_defaults() -> None:
    req = _request()
    assert req.temperature == 0.0
    assert req.seed == 0
    assert req.max_tokens == 1024
    assert req.response_format == "text"


def test_request_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        _request(bogus=1)


def test_request_is_frozen() -> None:
    with pytest.raises(ValidationError):
        _request().temperature = 0.5  # type: ignore[misc]  # frozen model, error expected


def test_bad_response_format_rejected() -> None:
    with pytest.raises(ValidationError):
        _request(response_format="xml")


def test_message_json_round_trip_keeps_umlauts() -> None:
    msg = Message(role="system", content="Kündigung")
    dumped = msg.model_dump_json()
    assert "Kündigung" in dumped
    assert Message.model_validate_json(dumped) == msg


def test_response_defaults_and_round_trip() -> None:
    resp = LLMResponse(
        text="Antwort",
        model="m",
        usage=Usage(prompt_tokens=3, completion_tokens=1),
        cost_usd=0.0,
        latency_ms=12.5,
        cached=False,
    )
    assert resp.provider == ""
    assert resp.fallback is False
    assert resp.model_version is None
    assert LLMResponse.model_validate_json(resp.model_dump_json()) == resp


def test_llm_error_keeps_attributes() -> None:
    err = LLMError("x", transient=True, status=429)
    assert err.transient is True
    assert err.status == 429
    assert isinstance(err, PruefstandError)
    assert str(err) == "x"


def test_llm_error_defaults() -> None:
    err = LLMError("y")
    assert err.transient is False
    assert err.status is None


def test_policy_violation_is_an_llm_error() -> None:
    assert issubclass(PolicyViolation, LLMError)
    assert PolicyViolation("p").transient is False


@pytest.mark.parametrize("bad", [0, -1, 1_000_000_000])
def test_max_tokens_is_bounded(bad: int) -> None:
    with pytest.raises(ValidationError):
        _request(max_tokens=bad)


def test_max_tokens_bounds_accept_the_usual_values() -> None:
    assert _request(max_tokens=1).max_tokens == 1
    assert _request(max_tokens=65536).max_tokens == 65536
