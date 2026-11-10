"""The manifest copy inside the Hugging Face layout (T4.7b S6, D1040)."""

from collections import Counter
from pathlib import Path

from pruefstand.core.enums import Split
from pruefstand.core.models.dataset import DatasetManifest
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import MANIFEST_FILE
from pruefstand.dataset.splits import assignment_summary
from pruefstand.dataset.validate import DERIVED_SPLITS


def write_hf_manifest(
    directory: Path, out: Path, grouped: dict[str, dict[Split, list[TestCase]]]
) -> None:
    """Write the manifest with ``splits``, ``blocks`` and ``judged_subset`` of the exported rows.

    Held-out and private cases are not exported, so the counts of the source manifest would not
    match the rows (``pruefstand validate dataset hf://...`` would report it); a split without
    any exported row is dropped.
    """
    manifest = DatasetManifest.model_validate_json((directory / MANIFEST_FILE).read_bytes())
    rows = [c for by_split in grouped.values() for cases in by_split.values() for c in cases]
    exported = Counter(c.split for c in rows)
    in_scope = [c for c in rows if c.split not in DERIVED_SPLITS]
    blocks, subset, _ = assignment_summary(in_scope, manifest.assignment_seed)
    update = {
        "splits": {s: exported[s] for s in manifest.splits if exported[s] > 0},
        "blocks": blocks,
        "judged_subset": subset,
    }
    (out / MANIFEST_FILE).write_text(
        manifest.model_copy(update=update).model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
