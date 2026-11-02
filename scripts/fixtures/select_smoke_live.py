"""Split the 40 hand-written slice cases into `smoke_live` (20) and `smoke` (20), T1.11 S1b.

The rule is fixed and has no randomness; each step takes the lowest case ids first:

1. one `leak_probe` per asking tenant (`kanzlei_mueller`, `stadtwerke_sued`);
2. two `unanswerable` cases;
3. two `injection` cases;
4. one `system_prompt_extraction` case;
5. `factual` cases with at least one gold citation up to exactly 20, keeping at least two English
   cases and preferring cases whose `cluster_id` is not yet in the selection.

Usage::

    uv run python scripts/fixtures/select_smoke_live.py            # write the three files
    uv run python scripts/fixtures/select_smoke_live.py --check    # exit 1 when they drifted
"""

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from pydantic import ValidationError

from pruefstand.core.enums import Category, Lang, Split
from pruefstand.core.models.dataset import DatasetManifest
from pruefstand.core.models.testcase import TestCase

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts" / "fixtures" / "slice_v1_cases.jsonl"
CORPUS_MANIFEST = ROOT / "corpus" / "slice_v1" / "manifest.json"
OUT_DIR = ROOT / "datasets" / "fixtures" / "slice_v1"
SMOKE_LIVE_SIZE = 20
ASKING_TENANTS = ("kanzlei_mueller", "stadtwerke_sued")
MIN_ENGLISH = 2
CREATED_AT = "2026-11-02T00:00:00Z"
LICENSES = {"laws_eurlex": "CC BY 4.0", "own": "CC BY 4.0"}


class SelectionError(ValueError):
    """The source cannot satisfy the selection rule or is malformed (the message names why)."""


def load_source(path: Path) -> list[TestCase]:
    """Read the hand-written source; the `split` field is set later, so a row must not carry it.

    Args:
        path: The source JSONL file.

    Returns:
        The cases (each with a placeholder split), in file order.

    Raises:
        SelectionError: A row is not JSON, sets `split`, or is not a valid `TestCase`.
    """
    cases: list[TestCase] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            msg = f"{path.name}:{number}: not JSON ({exc.msg})"
            raise SelectionError(msg) from exc
        if "split" in row:
            msg = f"{path.name}:{number}: the source must not set 'split' (select_smoke_live does)"
            raise SelectionError(msg)
        try:
            cases.append(TestCase.model_validate({**row, "split": Split.SMOKE.value}))
        except ValidationError as exc:
            first = exc.errors(include_url=False, include_input=False)[0]
            msg = f"{path.name}:{number}: {'.'.join(map(str, first['loc']))}: {first['msg']}"
            raise SelectionError(msg) from exc
    return cases


def _take(pool: Sequence[TestCase], count: int, what: str) -> list[TestCase]:
    if len(pool) < count:
        msg = f"{what}: need {count}, found {len(pool)}"
        raise SelectionError(msg)
    return list(pool[:count])


def _fill(pool: list[TestCase], chosen: list[TestCase], count: int) -> list[TestCase]:
    """Add ``count`` cases of ``pool``: English first up to the minimum, distinct clusters first."""
    picked: list[TestCase] = []
    clusters = {c.cluster_id for c in chosen}

    def sweep(candidates: list[TestCase], stop: int, *, english_only: bool = False) -> None:
        for fresh_only in (True, False):  # first the unseen clusters, then whatever is left
            for case in candidates:
                taken = sum(c.lang is Lang.EN for c in picked) if english_only else len(picked)
                if taken >= stop:
                    return
                if case in picked or (fresh_only and case.cluster_id in clusters):
                    continue
                picked.append(case)
                clusters.add(case.cluster_id)

    sweep([c for c in pool if c.lang is Lang.EN], MIN_ENGLISH, english_only=True)
    sweep(pool, count)
    return picked


def select(cases: Sequence[TestCase]) -> tuple[list[TestCase], list[TestCase]]:
    """Apply the rule; return ``(smoke_live, smoke)`` with the `split` field set, sorted by id.

    Args:
        cases: The source cases.

    Returns:
        The 20 selected cases and the remaining ones (disjoint, together all of ``cases``).

    Raises:
        SelectionError: A quota cannot be met; the message names the category and the counts.
    """
    ordered = sorted(cases, key=lambda c: c.id)

    def of(category: Category, tenant: str | None = None) -> list[TestCase]:
        return [c for c in ordered if c.category is category and tenant in {None, c.tenant}]

    chosen: list[TestCase] = []
    for tenant in ASKING_TENANTS:
        chosen += _take(of(Category.LEAK_PROBE, tenant), 1, f"leak_probe for tenant {tenant}")
    chosen += _take(of(Category.UNANSWERABLE), 2, Category.UNANSWERABLE.value)
    chosen += _take(of(Category.INJECTION), 2, Category.INJECTION.value)
    chosen += _take(of(Category.SYSTEM_PROMPT_EXTRACTION), 1, Category.SYSTEM_PROMPT_EXTRACTION.value)
    pool = [c for c in of(Category.FACTUAL) if c.gold_citations]
    need = SMOKE_LIVE_SIZE - len(chosen)
    chosen += _take(_fill(pool, chosen, need), need, "factual cases with a gold citation")
    ids = {c.id for c in chosen}
    live = [c.model_copy(update={"split": Split.SMOKE_LIVE}) for c in ordered if c.id in ids]
    rest = [c.model_copy(update={"split": Split.SMOKE}) for c in ordered if c.id not in ids]
    return live, rest


def _jsonl(cases: Iterable[TestCase]) -> str:
    rows = (c.model_dump(mode="json", exclude_defaults=True) for c in cases)
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def build_outputs(source: Path, corpus_manifest: Path) -> dict[str, str]:
    """Build the three dataset files as text (file name -> content); nothing is written.

    Args:
        source: The hand-written source JSONL.
        corpus_manifest: `corpus/slice_v1/manifest.json` (its `corpus_version` must match every case).

    Returns:
        `smoke_live.jsonl`, `smoke.jsonl` and `dataset_manifest.json` as text.

    Raises:
        SelectionError: The source is malformed, a case names another corpus version, or a quota fails.
    """
    corpus_version = json.loads(corpus_manifest.read_text(encoding="utf-8"))["corpus_version"]
    cases = load_source(source)
    for case in cases:
        if case.corpus_version != corpus_version:
            msg = f"{case.id}: corpus_version {case.corpus_version!r} != {corpus_version!r}"
            raise SelectionError(msg)
    live, rest = select(cases)
    manifest = DatasetManifest.model_validate(
        {
            "name": "slice",
            "version": "v1",
            "created_at": CREATED_AT,
            "corpus_version": corpus_version,
            "splits": {Split.SMOKE_LIVE: len(live), Split.SMOKE: len(rest)},
            "license_configs": LICENSES,
            "prompt_versions": {},
            "review": [],
        }
    )
    return {
        "smoke_live.jsonl": _jsonl(live),
        "smoke.jsonl": _jsonl(rest),
        "dataset_manifest.json": json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n",
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Write the dataset files, or with `--check` compare them; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--check", action="store_true", help="exit 1 when the files drifted")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="dataset directory")
    parser.add_argument("--source", type=Path, default=SOURCE, help="hand-written source JSONL")
    args = parser.parse_args(argv)
    try:
        outputs = build_outputs(args.source, CORPUS_MANIFEST)
    except SelectionError as exc:
        print(f"select_smoke_live: {exc}", file=sys.stderr)
        return 2
    if args.check:
        drifted = [
            name
            for name, text in outputs.items()
            if not (args.out / name).is_file()
            or (args.out / name).read_text(encoding="utf-8") != text
        ]
        for name in drifted:
            print(f"select_smoke_live: {args.out / name} differs from a fresh selection", file=sys.stderr)
        return 1 if drifted else 0
    args.out.mkdir(parents=True, exist_ok=True)
    for name, text in outputs.items():
        (args.out / name).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
