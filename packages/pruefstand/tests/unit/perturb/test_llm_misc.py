"""Small contracts of the LLM perturbations: registry, protocol, missing validator (T4.5)."""

import numpy as np
import pytest
from testsupport.loopback_script import serve_script
from testsupport.perturb_support import REWRITER, answers, client

from pruefstand.core.errors import ConfigError
from pruefstand.core.protocols import LLMPerturbation
from pruefstand.perturb import build_llm_perturbation, llm_perturbation_names
from pruefstand.perturb.register import rule_register
from pruefstand.perturb.rewriter import Rewriter

NAMES = ("compound_split", "register", "gender", "colloquial")


def test_names_are_stable() -> None:
    assert llm_perturbation_names() == NAMES


@pytest.mark.parametrize("name", NAMES)
def test_each_implements_the_protocol(name: str) -> None:
    p = build_llm_perturbation(name, Rewriter(REWRITER))
    assert isinstance(p, LLMPerturbation)
    assert p.name == name
    assert p.uses_llm is True
    assert p.version


def test_unknown_name() -> None:
    with pytest.raises(ConfigError):
        build_llm_perturbation("dates", Rewriter(REWRITER))


def test_sync_apply_is_refused() -> None:
    p = build_llm_perturbation("colloquial", Rewriter(REWRITER))
    with pytest.raises(ConfigError, match="aapply"):
        p.apply("Gilt das?", np.random.default_rng(0))


async def test_model_text_without_validator_is_a_config_error() -> None:
    p = build_llm_perturbation("colloquial", Rewriter(REWRITER))
    source = "Wann endet die Kündigungsfrist?"
    with (
        serve_script(answers("Wann endet die Frist denn?")) as (base, _),
        pytest.raises(ConfigError, match="RewriteValidator"),
    ):
        await p.aapply(source, client(base, REWRITER), np.random.default_rng(0))


@pytest.mark.parametrize(
    ("src", "out"),
    [
        ("Hast du mit dir Geduld?", "Haben Sie mit Ihnen Geduld?"),
        ("Gilt das für dich?", "Gilt das für Sie?"),
        ("Ist dein Vertrag befristet?", "Ist Ihr Vertrag befristet?"),
    ],
)
def test_du_to_sie_pronouns(src: str, out: str) -> None:
    got = rule_register(src)
    assert got is not None
    assert got.text == out


def test_unknown_du_verb_needs_the_llm() -> None:
    got = rule_register("Weißt du, ob du dich melden musst?")
    assert got is not None
    assert got.variant == "sie"
