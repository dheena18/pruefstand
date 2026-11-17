"""D1086: the infra status text fits GitHub's 140 chars and always keeps its ending."""

import pytest
from gate_orchestrator.status import MAX_DESCRIPTION, infra_summary

from pruefstand.core.enums import GateStatus
from pruefstand.report.github import status_for

LONG = [
    "model_reload: post-run health.sh exit 15 (placement:qwen3.8:27b-q8_0 "
    "size_vram 100 < size 200: not fully on the GPU)",
    "ollama_down: post-run health.sh exit 11 "
    "(endpoint:http://127.0.0.1:11434 /api/tags does not answer)",
    "x" * 500,
]


@pytest.mark.parametrize("infra_error", LONG)
@pytest.mark.parametrize(
    ("attempt", "ending"), [(1, "; retrying once"), (2, "; re-dispatch to retry")]
)
def test_description_is_at_most_140_chars_and_keeps_the_ending(
    infra_error: str, attempt: int, ending: str
) -> None:
    summary = infra_summary(infra_error, attempt)
    _, description = status_for(GateStatus.FAIL, summary, no_baseline=False, infra_error=True)
    assert len(description) <= MAX_DESCRIPTION == 140
    assert description.endswith(ending)
    assert description.startswith("executor infra error: " + infra_error[:20])


def test_short_text_is_unchanged() -> None:
    assert infra_summary("tunnel_lost: ssh exited", 1) == "tunnel_lost: ssh exited; retrying once"
