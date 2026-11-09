"""Stage files of ``build_dataset`` (T4.7a): ``stage_<n>_<name>.jsonl`` plus a ``.meta.json``.

A stage is *fresh* when its output exists and the meta file holds the hash of the stage's current
inputs (the settings it reads and the digests of the files it consumes); ``--resume`` skips fresh
stages. Writes are atomic (temp file, then rename), so an interrupted run never leaves a half
written stage that looks fresh.
"""

import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from pruefstand.core.errors import DatasetError
from pruefstand.core.hashing import stable_hash

STAGES = ("generate", "filter", "perturb", "attacks", "splits", "validate")


class StageMeta(BaseModel):
    """What a finished stage recorded: the input hash, the row count and its counters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    input_hash: str
    rows: int
    sha256: str
    counters: dict[str, int] = {}


def file_digest(path: Path) -> str:
    """Return the SHA-256 hex digest of ``path`` (empty string for a missing file)."""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def input_hash(name: str, settings: object, *digests: str) -> str:
    """Return the hash of a stage's inputs: its name, settings (a model or plain data), digests."""
    return stable_hash("build-stage", name, settings, list(digests))


class Workdir:
    """The work directory of one build (``<work_dir>/<build>/``)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, name: str) -> Path:
        """The output file of stage ``name``."""
        return self.root / f"stage_{STAGES.index(name) + 1}_{name}.jsonl"

    def _meta_path(self, name: str) -> Path:
        return self.path(name).with_suffix(".meta.json")

    def meta(self, name: str) -> StageMeta | None:
        """The meta record of ``name``, or None when absent or unreadable."""
        try:
            return StageMeta.model_validate_json(self._meta_path(name).read_text("utf-8"))
        except (OSError, ValidationError):
            return None

    def is_fresh(self, name: str, wanted: str) -> bool:
        """True when stage ``name`` was finished for the input hash ``wanted``."""
        meta = self.meta(name)
        return (
            meta is not None
            and meta.input_hash == wanted
            and meta.sha256 == file_digest(self.path(name))
        )

    def write(
        self,
        name: str,
        wanted: str,
        rows: Iterable[BaseModel],
        counters: dict[str, int] | None = None,
    ) -> StageMeta:
        """Write the rows of stage ``name`` and its meta record; return the record."""
        self.root.mkdir(parents=True, exist_ok=True)
        lines = [r.model_dump_json() for r in rows]
        target = self.path(name)
        temp = target.with_suffix(".tmp")
        temp.write_text("".join(f"{x}\n" for x in lines), encoding="utf-8", newline="\n")
        temp.replace(target)
        meta = StageMeta(
            name=name,
            input_hash=wanted,
            rows=len(lines),
            sha256=file_digest(target),
            counters=counters or {},
        )
        meta_temp = self._meta_path(name).with_suffix(".tmp")
        meta_temp.write_text(json.dumps(meta.model_dump(), sort_keys=True) + "\n", encoding="utf-8")
        meta_temp.replace(self._meta_path(name))
        return meta

    def read[M: BaseModel](self, name: str, model: type[M]) -> list[M]:
        """Read the rows of stage ``name``.

        Raises:
            DatasetError: The stage has not run, or a line is not a valid ``model``.
        """
        path = self.path(name)
        if not path.is_file():
            msg = f"stage {name} has no output ({path.name}); run it first"
            raise DatasetError(msg)
        rows: list[M] = []
        for number, line in enumerate(path.read_text("utf-8").splitlines(), start=1):
            try:
                rows.append(model.model_validate_json(line))
            except ValidationError as exc:
                msg = f"{path.name}:{number}: not a valid {model.__name__}"
                raise DatasetError(msg) from exc
        return rows

    def clear_from(self, names: Sequence[str]) -> None:
        """Delete the outputs of ``names`` (used when an earlier stage was re-run)."""
        for name in names:
            for path in (self.path(name), self._meta_path(name)):
                path.unlink(missing_ok=True)
