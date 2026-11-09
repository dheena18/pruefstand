"""Stage ``attacks`` of ``build_dataset``: injection, probe and refusal cases (T4.7a, T4.6).

* injection cases: ``build_attack_set`` from the ``attacks`` block of ``corpus.yaml``, checked
  against the version the corpus manifest pins (``check_attack_versions``);
* probes: leak, filter-bypass and system-prompt extraction, from the canary registry of the corpus
  (``canaries.public.json``);
* refusal cases: the own near-miss and off-topic templates, per tenant, against the citation keys
  the tenant can retrieve.

All cases get the real ``corpus_version`` (the generators leave a placeholder).
"""

from collections import defaultdict
from pathlib import Path

import numpy as np

from pruefstand.attacks.probes import (
    make_filter_bypass_probes,
    make_leak_probes,
    make_system_prompt_probes,
)
from pruefstand.attacks.refusal import make_own_unanswerable
from pruefstand.core.config import CorpusBuildConfig
from pruefstand.core.config_loader import load_model
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.settings import PruefstandSettings
from pruefstand.dataset.sampling import load_chunks
from pruefstand.pipeline.attack_set import attack_tenants, build_attack_set, check_attack_versions
from pruefstand.pipeline.build_context import BuildContext, StageResult

CANARIES_FILE = "canaries.public.json"
PUBLIC_TENANT = "shared_public"
_MIN_OWNERS = 2


def _by_id(case: TestCase) -> str:
    return case.id


def _indexed(ctx: BuildContext) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    keys: dict[str, set[str]] = defaultdict(set)
    for chunk in load_chunks(ctx.cfg.corpus_dir):
        if chunk.citation_key and not chunk.is_attack:
            keys[chunk.tenant].add(chunk.citation_key)
    shared = keys.get(PUBLIC_TENANT, set())
    indexed = {t: k | shared for t, k in keys.items() if t != PUBLIC_TENANT}
    laws = {t: {k.rsplit(" ", 1)[-1] for k in v} for t, v in indexed.items()}
    return indexed, laws


def _injection(ctx: BuildContext, tenants: list[str]) -> list[TestCase]:
    if ctx.cfg.corpus_config is None:
        return []
    corpus_cfg = load_model(ctx.cfg.corpus_config, CorpusBuildConfig)
    if corpus_cfg.attacks is None:
        return []
    secret = PruefstandSettings().attack_key
    key = None if secret is None else secret.get_secret_value().encode()
    attack = build_attack_set(corpus_cfg.attacks, tenants, key)
    check_attack_versions(
        ctx.manifest.sources, attack.sources(), expect_secret_markers=key is not None
    )
    return attack.cases


def _probes(ctx: BuildContext, tenants: list[str]) -> list[TestCase]:
    """System-prompt probes always; leak and filter-bypass probes for the tenants with canaries.

    A probe asks as one tenant about another tenant's canary, so at least two customer tenants
    must own one; with fewer there is nothing to leak and those probes are left out.
    """
    path = Path(ctx.cfg.corpus_dir) / CANARIES_FILE
    cases = make_system_prompt_probes()
    if not path.is_file():
        return cases
    registry = CanaryRegistry.model_validate_json(path.read_text("utf-8"))
    owners = {c.tenant for c in registry.canaries}
    customers = [t for t in attack_tenants(tenants) if t in owners]
    if len(customers) < _MIN_OWNERS:
        return cases
    return [
        *make_leak_probes(registry, customers),
        *make_filter_bypass_probes(registry, customers),
        *cases,
    ]


async def attacks_stage(ctx: BuildContext) -> StageResult:
    """Run the ``attacks`` stage; return the cases (provisional split ``full``) and counters.

    Raises:
        ConfigError: ``corpus_config`` is unreadable or invalid.
        DatasetError: The attack set does not match the corpus, or a refusal template is answerable.
    """
    indexed, laws = _indexed(ctx)
    tenants = sorted({*indexed, PUBLIC_TENANT})
    rng = np.random.default_rng([ctx.cfg.seed, 7])
    injection = _injection(ctx, tenants)
    probes = _probes(ctx, tenants)
    refusal = make_own_unanswerable(indexed, rng, laws=laws if ctx.cfg.check_refusal_laws else None)
    cases = [
        c.model_copy(update={"corpus_version": ctx.manifest.corpus_version})
        for c in (*injection, *probes, *refusal)
    ]
    counters = {"injection": len(injection), "probes": len(probes), "refusal": len(refusal)}
    ordered = sorted(cases, key=_by_id)
    return ordered, counters
