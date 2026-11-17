"""Write the pre-deploy probe dataset (T8.5 S6, ADR-0012): leak, bypass and prompt probes.

The set is the ``leak_probe``, ``filter_bypass`` and ``system_prompt_extraction`` cases of the
fixture datasets plus the probes ``pruefstand.attacks`` generates over the PUBLIC canary registry of
the demo corpus, all in split ``full`` and stamped with its corpus version. Only a
``*.public.json`` registry is accepted: the held-out one never reaches a probe.

Exit codes: 0 written, 2 usage (not a public registry, unreadable input, id clash).
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pruefstand.attacks.canary import TENANT_PREFIX
from pruefstand.attacks.probes import (
    make_filter_bypass_probes,
    make_leak_probes,
    make_system_prompt_probes,
)
from pruefstand.core.enums import Category, Split
from pruefstand.core.errors import PruefstandError
from pruefstand.core.ids import TenantId
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import build_manifest, read_dataset, write_dataset

CATEGORIES = (Category.LEAK_PROBE, Category.FILTER_BYPASS, Category.SYSTEM_PROMPT_EXTRACTION)
DEFAULT_FIXTURES = ("datasets/fixtures/slice_v1", "datasets/fixtures/mini_v0")
DEFAULT_REGISTRY = "corpus/slice_v1/canaries.public.json"


def fixture_probes(directories: Sequence[Path]) -> list[TestCase]:
    """The probe-category cases of the fixture datasets, each once (by id), any split."""
    found: dict[str, TestCase] = {}
    for directory in directories:
        for cases in read_dataset(directory).cases.values():
            for case in cases:
                if case.category in CATEGORIES:
                    found.setdefault(case.id, case)
    return list(found.values())


def generated_probes(registry: CanaryRegistry) -> list[TestCase]:
    """Leak, filter-bypass and system-prompt probes for the customer tenants of the registry."""
    tenants = [
        TenantId(t) for t in sorted({c.tenant for c in registry.canaries} & set(TENANT_PREFIX))
    ]
    return (
        make_leak_probes(registry, tenants)
        + make_filter_bypass_probes(registry, tenants)
        + make_system_prompt_probes()
    )


def build(
    fixtures: Sequence[Path], registry_path: Path, corpus_version: str
) -> tuple[list[TestCase], CanaryRegistry]:
    """All probe cases in split ``full``, stamped with ``corpus_version``, unique by id."""
    registry = CanaryRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
    cases: dict[str, TestCase] = {}
    for case in fixture_probes(fixtures) + generated_probes(registry):
        stamped = case.model_copy(update={"split": Split.FULL, "corpus_version": corpus_version})
        if cases.setdefault(stamped.id, stamped) != stamped:
            msg = f"two different probes share the id {stamped.id!r}"
            raise PruefstandError(msg)
    return list(cases.values()), registry


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: ``--out DIR --corpus-version V [--fixtures DIR ...] [--registry FILE]``."""
    parser = argparse.ArgumentParser(description="Write the pre-deploy leak-probe dataset.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--corpus-version", required=True)
    parser.add_argument(
        "--fixtures", type=Path, nargs="+", default=[Path(p) for p in DEFAULT_FIXTURES]
    )
    parser.add_argument("--registry", type=Path, default=Path(DEFAULT_REGISTRY))
    args = parser.parse_args(argv)
    if not args.registry.name.endswith(".public.json"):
        sys.stderr.write(
            f"build_leak_probe_set: {args.registry} is not a public registry (*.public.json)\n"
        )
        return 2
    try:
        cases, _ = build(args.fixtures, args.registry, args.corpus_version)
        manifest = build_manifest("leakprobe", "v1", args.corpus_version, cases, seed=0)
        write_dataset(args.out, cases, manifest)
    except (PruefstandError, OSError, ValueError) as exc:
        sys.stderr.write(f"build_leak_probe_set: {exc}\n")
        return 2
    sys.stdout.write(f"build_leak_probe_set: {len(cases)} probes in {args.out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
