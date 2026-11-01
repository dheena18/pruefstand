"""vcr configuration shared by the unit and live conftests: an allow-list, never a deny-list.

Only ``content-type`` / ``accept`` of a request and ``content-type`` / ``content-length`` of a
response reach a cassette (no cookies, request ids, user agents, ``x-*``). Every recorded text must
also pass ``assert_no_secrets``; otherwise the recording is refused.
"""

from typing import Any

from pruefstand.llm.scrub import assert_no_secrets

REQUEST_HEADERS = frozenset({"content-type", "accept"})
RESPONSE_HEADERS = frozenset({"content-type", "content-length"})


def scrub_request(request: Any) -> Any:
    request.headers = {k: v for k, v in request.headers.items() if k.lower() in REQUEST_HEADERS}
    assert_no_secrets(request.uri)
    body = request.body
    assert_no_secrets(
        body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body or "")
    )
    return request


def scrub_response(response: dict[str, Any]) -> dict[str, Any]:
    response["headers"] = {
        k: v for k, v in response["headers"].items() if k.lower() in RESPONSE_HEADERS
    }
    body = response["body"]["string"]
    assert_no_secrets(body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body))
    return response


VCR_CONFIG: dict[str, Any] = {
    "match_on": ["method", "path", "body"],
    "allow_playback_repeats": False,
    "before_record_request": scrub_request,
    "before_record_response": scrub_response,
}
