"""Distinctive semantic values and the public-text collision check (T2.6, D724)."""

import numpy as np
import pytest
from private_doc_plan import plan_all, plan_documents

from pruefstand.attacks import facts
from pruefstand.attacks.canary import TENANT_PREFIX, semantic_variants
from pruefstand.attacks.collision import public_collisions
from pruefstand.attacks.facts import MIN_VALUE, check_templates, fact_templates, make_semantic_fact
from pruefstand.core.errors import DatasetError
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.attacks import Canary


def canary(number: int, unit: str) -> Canary:
    return Canary(
        token=f"{number} {unit}",
        tenant=TenantId("kanzlei_mueller"), doc_id=DocId("priv-km-01"),
        kind="semantic", fact="x", probe_question="y",
        forbidden_answer=semantic_variants(number, unit),
    )  # fmt: skip


def test_every_template_range_starts_at_three_digits() -> None:
    for tenant, rows in fact_templates().items():
        assert all(row.low >= MIN_VALUE for row in rows), tenant


def test_a_low_range_is_refused() -> None:
    low = facts.FactTemplate(
        doc_type="t",
        sentence="{party} {value}",
        probe="p",
        unit="Tage",
        low=8,
        high=99,
        person=False,
    )
    with pytest.raises(DatasetError, match="need >= 101"):
        check_templates({"kanzlei_mueller": (low,)})


@pytest.mark.parametrize("tenant", list(TENANT_PREFIX))
def test_generated_values_have_three_digits(tenant: str) -> None:
    rng = np.random.default_rng(3)
    for index in range(12):
        fact = make_semantic_fact(tenant, index, rng, set())
        assert int(fact.value.split()[0].replace(".", "")) >= MIN_VALUE


def test_plan_values_are_distinct_across_tenants_and_independent_of_the_selection() -> None:
    everything = plan_all(8, 7)
    values = [p.fact.value for plans in everything.values() for p in plans]
    assert len(values) == len(set(values)) == 24
    # a single-tenant plan with its own empty set may differ; plan_all is the one the script uses
    assert plan_all(8, 7) == everything
    assert plan_documents("kanzlei_mueller", 8, 7) == everything["kanzlei_mueller"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Die Frist beträgt 113 Tage.", ["priv-km-01"]),
        ("nach einhundertdreizehn Tagen", ["priv-km-01"]),
        ("113-tägige Frist", ["priv-km-01"]),
        ("113 Euro", []),
        ("Die Frist beträgt elf Stunden.", []),
    ],
)
def test_public_collisions(text: str, expected: list[str]) -> None:
    found = public_collisions([canary(113, "Tage")], [text])
    assert found == expected


def test_token_canaries_are_ignored() -> None:
    token = Canary(
        token="CANARY-KM-000000",  # noqa: S106  (synthetic canary)
        tenant=TenantId("kanzlei_mueller"), doc_id=DocId("d"),
        kind="token", fact=None, probe_question=None, forbidden_answer="CANARY-KM-000000",
    )  # fmt: skip
    assert public_collisions([token], ["CANARY-KM-000000"]) == []
