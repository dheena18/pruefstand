"""``pruefstand ingest``: load the sources, assign tenants, chunk and write a corpus (T2.5).

Order, without circularity: load -> ``assign_tenants`` -> chunk -> serialise the sorted chunks and
build the provisional manifest -> ``core.fingerprint.corpus_version`` -> ``write_corpus`` into
``<out>/<corpus_version>``. The build date is an argument, so the same inputs and date give the
same bytes. Loader problems, an unpinned source, an empty tenant or a document that appears
twice stop the build before anything is written.
"""

import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from pruefstand.core.config import CorpusBuildConfig
from pruefstand.core.config_loader import load_model
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.fingerprint import corpus_version
from pruefstand.core.logging import get_logger
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.corpus import Chunk, CorpusManifest, Document
from pruefstand.core.protocols import Loader
from pruefstand.core.settings import PruefstandSettings
from pruefstand.ingest.eurlex import EurLexLoader
from pruefstand.ingest.gii_xml import GiiXmlLoader
from pruefstand.ingest.oldp import OldpLoader
from pruefstand.ingest.pins import SYNTHETIC_PIN, load_pins, pin_for
from pruefstand.ingest.tenants import assign_tenants
from pruefstand.ingest.writer import provisional_manifest, write_corpus
from pruefstand.pipeline.ingest_chunks import chunk_documents
from pruefstand.pipeline.ingest_private import load_private_documents, write_registry

_log = get_logger(__name__)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_PINNED_PREFIXES = ("gii:", "eurlex:", "oldp")
_SHOWN_PROBLEMS = 10
_PUBLIC_TENANT = "shared_public"  # visible to every tenant: no private or attack documents


def _extra_documents(cfg: CorpusBuildConfig) -> list[Document]:
    """Hook for documents that are not loaded from a public source.

    T4.6 returns the injection documents here (the synthetic private documents of T2.6 come from
    ``corpus.yaml: private_docs`` through ``pipeline.ingest_private``). Each document must
    already carry its tenant (one of the plan's) and a unique
    ``doc_id``; they bypass the rules of the plan, so everything else is checked in
    :func:`_checked_extras`.

    Args:
        cfg: The build config.

    Returns:
        Empty for now.
    """
    del cfg
    return []


def _checked_extras(
    cfg: CorpusBuildConfig, public_ids: set[str], private: list[Document]
) -> list[Document]:
    extras = [*private, *_extra_documents(cfg)]
    declared = set(cfg.plan.tenants)
    seen = set(public_ids)
    for doc in extras:
        if doc.tenant not in declared:
            msg = f"{doc.doc_id}: tenant {doc.tenant!r} is not one of the plan's tenants"
            raise ConfigError(msg)
        if doc.tenant == _PUBLIC_TENANT:
            msg = f"{doc.doc_id}: an extra document must not join {_PUBLIC_TENANT}"
            raise ConfigError(msg)
        if doc.source.startswith(_PINNED_PREFIXES):
            msg = f"{doc.doc_id}: an extra document must not claim the pinned source {doc.source!r}"
            raise ConfigError(msg)
        if doc.doc_id in seen:
            msg = f"{doc.doc_id}: document id is already used (a document belongs to one tenant)"
            raise DatasetError(msg)
        seen.add(doc.doc_id)
    return extras


class _Sources:
    """The configured loaders; remembers them to report their problems after the load."""

    def __init__(self, cfg: CorpusBuildConfig, raw_root: Path) -> None:
        self.raw_root = raw_root
        self.loaders: list[tuple[str, Loader, Path]] = []
        plan = cfg.plan
        if "gii" in cfg.loaders:
            slugs = [s.split(":", 1)[1] for s in plan.sources("gii")]
            self.loaders.append(("gii", GiiXmlLoader(expected=slugs), raw_root / "gii"))
        if "eurlex" in cfg.loaders:
            celex = [s.split(":", 1)[1] for s in plan.sources("eurlex")]
            self.loaders.append(("eurlex", EurLexLoader(expected=celex), raw_root / "eurlex"))
        if "oldp" in cfg.loaders:
            path = raw_root / "hf" / "oldp_decisions"
            self.loaders.append(("oldp", OldpLoader(), path))

    def documents(self) -> Iterator[Document]:
        """Yield the documents of all loaders in a fixed order (gii, eurlex, oldp)."""
        for _, loader, path in self.loaders:
            yield from loader.load(path)

    def problems(self) -> list[str]:
        """Describe every problem the loaders counted, as <source> <kind>."""
        found: list[str] = []
        for _, loader, _ in self.loaders:
            if isinstance(loader, GiiXmlLoader):
                found += [f"gii:{p.law} {p.kind}" for p in loader.stats.problems]
            elif isinstance(loader, EurLexLoader):
                found += [f"eurlex:{p.celex} {p.kind}" for p in loader.stats.problems]
            elif isinstance(loader, OldpLoader):
                log = loader.stats.problems
                found += [f"oldp:{p.source} {p.kind}" for p in log]
                found += ["oldp: further problems of the same kinds"] * (log.total - len(log))
        return found


def _check_date(date_tag: str) -> None:
    try:
        if _DATE.fullmatch(date_tag):
            date.fromisoformat(date_tag)
            return
    except ValueError:
        pass
    msg = f"--date must be a calendar date YYYY-MM-DD, got {date_tag[:20]!r}"
    raise ConfigError(msg)


def _resolve(path: Path, base: Path) -> Path:
    return path if path.is_absolute() else base / path


def _check_limit(chunks: list[Chunk], cfg: CorpusBuildConfig) -> None:
    if len(chunks) > cfg.max_chunks:
        msg = f"more than max_chunks={cfg.max_chunks} chunks; raise the limit in corpus.yaml"
        raise DatasetError(msg)


def _collect(cfg: CorpusBuildConfig, sources: _Sources) -> tuple[list[Chunk], set[str], set[str]]:
    """Load, assign and chunk; return the chunks, the public doc ids and the sources seen."""
    ids: set[str] = set()
    names: set[str] = set()

    def tracked() -> Iterator[Document]:
        for doc in assign_tenants(sources.documents(), cfg.plan):
            ids.add(doc.doc_id)
            names.add(doc.source)
            yield doc

    chunks: list[Chunk] = []
    for chunk in chunk_documents(tracked(), cfg.max_tokens):
        chunks.append(chunk)
        _check_limit(chunks, cfg)
    return chunks, ids, names


def _private(cfg: CorpusBuildConfig, base: Path) -> tuple[list[Document], CanaryRegistry | None]:
    """Load the planted private documents (and the held-out ones when configured), if enabled."""
    if cfg.private_docs is None:
        return [], None
    return load_private_documents(cfg.private_docs, base, PruefstandSettings().heldout_dir)


def build_corpus(config_path: Path, out: Path, date_tag: str) -> CorpusManifest:
    """Build the corpus of ``config_path`` into ``<out>/<corpus_version>``.

    Args:
        config_path: ``corpus.yaml``; relative paths in it are relative to its directory.
        out: Parent directory of the corpus versions (``corpus/``).
        date_tag: Build date ``YYYY-MM-DD`` (the CLI passes today unless ``--date`` is given).

    Returns:
        The written manifest.

    Raises:
        ConfigError: Invalid config or date, a document no rule claims (or two claim), an
            unpinned source, or an invalid extra document.
        DatasetError: No approved private document for a customer tenant, loader problems above
            ``max_problems``, a tenant without chunks, more than
            ``max_chunks`` chunks, a repeated document, or an inconsistent corpus.
    """
    _check_date(date_tag)
    cfg = load_model(config_path, CorpusBuildConfig)
    base = config_path.resolve().parent
    pins_file = _resolve(cfg.sources_file, base)
    pins = load_pins(pins_file)
    sources = _Sources(cfg, _resolve(cfg.raw_root, base))
    chunks, public_ids, public_sources = _collect(cfg, sources)
    problems = sources.problems()
    if len(problems) > cfg.max_problems:
        shown = "; ".join(problems[:_SHOWN_PROBLEMS])
        msg = f"{len(problems)} loader problem(s), at most {cfg.max_problems} allowed: {shown}"
        raise DatasetError(msg)
    private, registry = _private(cfg, base)
    extras = _checked_extras(cfg, public_ids, private)
    for chunk in chunk_documents(extras, cfg.max_tokens):
        chunks.append(chunk)
        _check_limit(chunks, cfg)
    empty = sorted(set(cfg.plan.tenants) - {c.tenant for c in chunks})
    if empty:
        msg = f"tenant(s) without any chunk: {', '.join(empty)}"
        raise DatasetError(msg)
    pinned = {s: pin_for(s, pins, pins_file) for s in sorted(public_sources)}
    pinned.update({d.source: SYNTHETIC_PIN for d in extras})
    version = corpus_version(provisional_manifest(chunks, pinned), date_tag)
    manifest = write_corpus(chunks, out / version, version, sources=pinned)
    if cfg.private_docs is not None and registry is not None:
        write_registry(registry, _resolve(cfg.private_docs.registry_dir, base), version)
    _log.info(
        "corpus_written", corpus_version=version, chunks=len(chunks), tenants=manifest.tenants
    )
    return manifest
