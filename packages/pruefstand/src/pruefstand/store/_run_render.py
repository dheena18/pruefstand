"""``render_files``: the files of a run directory as bytes, with their SHA-256 in ``run.json``."""

import hashlib
import io

from pruefstand.core.models.run import RunResults
from pruefstand.store._run_files import jsonl, manifest_text, results_frame

DATA_FILES = ("results.parquet", "responses.jsonl", "scored.jsonl")


def render_files(results: RunResults) -> dict[str, bytes]:
    """Serialise ``results`` exactly as ``ArtifactStore.write_run`` would, in memory.

    The data files come first; their SHA-256 values go into ``run.json``
    (``RunManifest.artifact_sha256``), which is rendered last. Stores that compress or filter
    files hash and parse these very bytes, never a re-opened path.

    Args:
        results: The run.

    Returns:
        File name to content for ``run.json``, ``results.parquet``, ``responses.jsonl`` and
        ``scored.jsonl``.

    Raises:
        ValueError: A string cannot be encoded (lone surrogate) or serialised.
        polars.exceptions.PolarsError: The parquet view cannot be built.
    """
    parquet = io.BytesIO()
    results_frame(results.values).write_parquet(parquet, compression="zstd")
    files = {
        "results.parquet": parquet.getvalue(),
        "responses.jsonl": jsonl(results.records).encode("utf-8"),
        "scored.jsonl": jsonl(results.values).encode("utf-8"),
    }
    sums = {name: hashlib.sha256(files[name]).hexdigest() for name in DATA_FILES}
    manifest = results.manifest.model_copy(update={"artifact_sha256": sums})
    return {"run.json": manifest_text(manifest).encode("utf-8"), **files}
