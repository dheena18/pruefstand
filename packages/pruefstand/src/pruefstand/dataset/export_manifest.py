"""The manifest copy inside the Hugging Face layout (T4.7b S6, D1040)."""

from collections import Counter
from pathlib import Path

from pruefstand.core.enums import Split
from pruefstand.core.models.dataset import DatasetManifest
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import MANIFEST_FILE


def write_hf_manifest(
    directory: Path, out: Path, grouped: dict[str, dict[Split, list[TestCase]]]
) -> None:
    """Copy the manifest with ``splits`` counting the exported rows (held-out ones are dropped)."""
    manifest = DatasetManifest.model_validate_json((directory / MANIFEST_FILE).read_bytes())
    exported = Counter[Split]()
    for by_split in grouped.values():
        for split, rows in by_split.items():
            exported[split] += len(rows)
    splits = {s: exported[s] for s in manifest.splits if exported[s] > 0}
    (out / MANIFEST_FILE).write_text(
        manifest.model_copy(update={"splits": splits}).model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
