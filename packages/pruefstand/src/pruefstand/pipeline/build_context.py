"""What every stage of ``build_dataset`` receives (T4.7a)."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from pruefstand.core.config import DatasetBuildConfig
from pruefstand.core.models.corpus import CorpusManifest
from pruefstand.pipeline.build_clients import BuildClients
from pruefstand.pipeline.build_state import Workdir


@dataclass(frozen=True)
class BuildContext:
    """Settings, directories and clients of one build.

    Attributes:
        cfg: The build configuration (paths already resolved).
        work: The work directory of this build.
        clients: Factories of the model and embedding clients.
        manifest: The corpus manifest (``corpus_version``, pinned sources).
        only: ``--only``: restrict ``generate`` to this prompt id or version.
    """

    cfg: DatasetBuildConfig
    work: Workdir
    clients: BuildClients
    manifest: CorpusManifest
    root: Path
    only: str | None = None


StageResult = tuple[Sequence[BaseModel], dict[str, int]]
"""The rows a stage writes and its counters (``dropped_mixed_license`` and so on)."""
