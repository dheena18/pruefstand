"""``PrivateDocsConfig``: the ``private_docs`` block of ``corpus.yaml`` (T2.6)."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class PrivateDocsConfig(BaseModel):
    """Where the approved synthetic private documents are and how their canaries are planted.

    Attributes:
        dir: ``<dir>/<tenant>/*.md`` (human-approved; the ``_drafts`` folder is never read).
        seed: Seed of the token canaries: the same seed and documents give the same corpus bytes.
        registry_dir: The public registry goes to ``<registry_dir>/<corpus_version>/canaries.json``
            (outside ``corpus/``, which the rag-demo indexer reads).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dir: Path = Path("datasets/private_docs")
    seed: int = Field(ge=0)
    registry_dir: Path = Path("datasets/canaries")
