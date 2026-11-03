"""Rewriter: external model for public text, local model when the data guard blocks (ADR-0019)."""

import pytest
from testsupport.loopback_script import serve_script
from testsupport.perturb_support import KEY_ENV, LOCAL_REWRITER, REWRITER, answers, client

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.errors import PolicyViolation
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.attacks import Canary, CanaryRegistry
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder
from pruefstand.perturb.rewriter import LocalTarget, Rewriter, clean_rewrite

CANARY = CanaryRegistry(
    canaries=(
        Canary(
            token="ZXQ-CANARY-7731",  # noqa: S106  (synthetic canary token)
            tenant=TenantId("acme"),
            doc_id=DocId("d1"),
            kind="token",
            fact=None,
            probe_question=None,
            forbidden_answer=None,
        ),
    )
)
SECRET_Q = "Was bedeutet ZXQ-CANARY-7731 in der Gehaltsliste?"  # noqa: S105  (synthetic)


@pytest.mark.parametrize(
    ("raw", "out"),
    [
        ("  Wann darf mein Chef mich rauswerfen?  ", "Wann darf mein Chef mich rauswerfen?"),
        ('"Wann darf mein Chef mich rauswerfen?"', "Wann darf mein Chef mich rauswerfen?"),
        ("Umformulierte Frage: Wann darf er?", "Wann darf er?"),
        ("<think>hm</think>\nWann darf er?\nDas ist eine Erklärung.", "Wann darf er?"),
        ("", ""),
    ],
)
def test_clean_rewrite(raw: str, out: str) -> None:
    assert clean_rewrite(raw) == out


async def test_public_question_goes_to_the_external_model() -> None:
    with serve_script(answers("Wann endet die Frist?")) as (ext, es):
        got = await Rewriter(REWRITER).rewrite(
            client(ext, REWRITER, canaries=CANARY),
            "colloquial_de",
            question="Wie lautet die Frist?",
        )
    assert (got.text, got.model, got.local) == ("Wann endet die Frist?", REWRITER, False)
    assert es.posts() == 1


async def test_blocked_question_is_rewritten_locally_and_never_sent_out() -> None:
    with (
        serve_script(answers("nie gesendet")) as (ext, es),
        serve_script(answers("Lokal umformuliert?")) as (loc, ls),
    ):
        rewriter = Rewriter(REWRITER, LocalTarget(client(loc, LOCAL_REWRITER), LOCAL_REWRITER))
        got = await rewriter.rewrite(
            client(ext, REWRITER, canaries=CANARY), "colloquial_de", question=SECRET_Q
        )
    assert (got.text, got.model, got.local) == ("Lokal umformuliert?", LOCAL_REWRITER, True)
    assert es.posts() == 0
    assert ls.posts() == 1


async def test_blocked_question_without_local_target_raises_policy_violation() -> None:
    with serve_script(answers("x")) as (ext, es), pytest.raises(PolicyViolation):
        await Rewriter(REWRITER).rewrite(
            client(ext, REWRITER, canaries=CANARY), "colloquial_de", question=SECRET_Q
        )
    assert es.posts() == 0


async def test_other_policy_violations_surface_instead_of_going_local() -> None:

    with serve_script(answers("x")) as (ext, es), serve_script(answers("lokal")) as (loc, ls):
        denied = LLMPolicyConfig(allowed_providers=("ollama",))  # github is not allowed
        ext_client = LLMClient(
            LiteLLMBackend(REWRITER, api_base=f"{ext}/v1", api_key_env=KEY_ENV, timeout_s=30),
            None,
            Budget(None, None),
            CallRecorder(),
            LLMPolicy(denied, CanaryRegistry(canaries=())),
        )
        rewriter = Rewriter(REWRITER, LocalTarget(client(loc, LOCAL_REWRITER), LOCAL_REWRITER))
        with pytest.raises(PolicyViolation):
            await rewriter.rewrite(ext_client, "colloquial_de", question="Wann endet die Frist?")
    assert ls.posts() == 0
    assert es.posts() == 0
