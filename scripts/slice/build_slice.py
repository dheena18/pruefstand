"""Build ``corpus/slice_v1``: the committed 5-law slice plus synthetic tenant documents (T1.13 S1).

``uv run python scripts/slice/build_slice.py`` reads the pinned downloads in ``data/raw``
(``make data``) and writes ``<tenant>.chunks.jsonl``, ``manifest.json`` and
``canaries.public.json``. The output is
deterministic: the same inputs give the same bytes and the same ``corpus_version``
(``slice-<latest pin date>.<8 hex of the file hashes>``; ``created_at`` is that pin date).

Tenants: ``kanzlei_mueller`` (KSchG §§ 1-4, ArbZG §§ 3-5), ``stadtwerke_sued`` (DSGVO Art. 5-6 in
German and English, BDSG § 26), ``shared_public`` (BGB §§ 620-626), ``versicherung_nord`` (private
documents only), each plus the hand-written documents under ``handwritten/`` (canaries, planted
injections). This is a script: it may import ``pruefstand``; the rag-demo app never does.
"""

import argparse
import hashlib
import json
import re
from collections.abc import Iterator, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from pruefstand.core.enums import Lang
from pruefstand.core.ids import ChunkId, DocId, TenantId
from pruefstand.core.models.corpus import Chunk
from pruefstand.ingest.chunkers.paragraph import ParagraphChunker, split_absaetze
from pruefstand.ingest.gii_xml import GiiXmlLoader

try:
    from slice.eurlex_min import parse_articles
except ModuleNotFoundError:  # run as a script: sys.path[0] is scripts/slice
    from eurlex_min import parse_articles  # type: ignore[import-not-found,no-redef]  # see above

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HANDWRITTEN = HERE / "handwritten"
CELEX = "32016R0679"
DSGVO_ARTICLES = (5, 6)
GII_PICK: dict[str, tuple[str, str, frozenset[int]]] = {
    # law abbreviation -> (tenant, source id, section numbers)
    "KSchG": ("kanzlei_mueller", "gii:kschg", frozenset(range(1, 5))),
    "ArbZG": ("kanzlei_mueller", "gii:arbzg", frozenset(range(3, 6))),
    "BGB": ("shared_public", "gii:bgb", frozenset(range(620, 627))),
    "BDSG": ("stadtwerke_sued", "gii:bdsg", frozenset({26})),
}
TENANTS = ("kanzlei_mueller", "shared_public", "stadtwerke_sued", "versicherung_nord")
SYNTHETIC_LICENSE = "CC0-1.0"
SPLIT_ABOVE_TOKENS = 350  # a § longer than this becomes one chunk per Absatz (e5 reads 512 tokens)
_EN_PARAGRAPH = re.compile(r"^\d+\.\s")
_FRONT = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


def _pins(sources: Path) -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(sources.read_text(encoding="utf-8"))
    return {row["id"]: row for row in data["sources"]}


def _gii_chunks(raw: Path) -> Iterator[Chunk]:
    chunker = ParagraphChunker(max_tokens=SPLIT_ABOVE_TOKENS)
    for doc in GiiXmlLoader().load(raw / "gii"):
        pick = GII_PICK.get(doc.law_abbrev or "")
        suffix = doc.doc_id.rsplit("-", 1)[-1]
        if pick is None or not suffix.isdigit() or int(suffix) not in pick[2]:
            continue
        for chunk in chunker.chunk(doc):
            yield chunk.model_copy(update={"tenant": TenantId(pick[0])})


def _paragraphs(text: str, lang: str) -> list[tuple[str, str]]:
    """Split an article into ``(label, text)`` per numbered paragraph ("(1)" de, "1." en)."""
    if lang == "de":
        return split_absaetze(text) or [("", text)]
    parts: list[list[str]] = []
    for line in text.split("\n"):
        if _EN_PARAGRAPH.match(line) or not parts:
            parts.append([line])
        else:
            parts[-1].append(line)
    return [
        (f"Para. {p[0].split('.')[0]}" if _EN_PARAGRAPH.match(p[0]) else "", "\n".join(p))
        for p in parts
    ]


def _dsgvo_chunks(raw: Path, pin_date: str) -> Iterator[Chunk]:
    for lang in ("de", "en"):
        text = (raw / "eurlex" / CELEX / f"{lang}.html").read_bytes()
        for article in parse_articles(text, DSGVO_ARTICLES):
            doc_id = f"eurlex-{CELEX.lower()}-art-{article.number}-{lang}"
            parts = _paragraphs(article.text, lang)
            for index, (label, body) in enumerate(parts):
                head = f"{article.title}\n" if index == 0 else ""
                yield Chunk(
                    chunk_id=ChunkId(f"{doc_id}#{index}"),
                    doc_id=DocId(doc_id),
                    tenant=TenantId("stadtwerke_sued"),
                    lang=Lang(lang),
                    text=head + body,
                    citation_key=f"Art. {article.number} DSGVO",
                    section=label or None,
                    parallel_id=f"{CELEX}:art-{article.number}",
                    version_date=date.fromisoformat(pin_date),
                    license="eurlex-legal-notice",
                    source=f"eurlex:{CELEX}",
                )


def _unwrap(body: str) -> str:
    """Join hard-wrapped prose lines; table rows, footnotes and blank-line paragraphs stay lines."""
    lines: list[str] = []
    for raw in body.strip().split("\n"):
        line = raw.strip()
        if not line:
            lines.append("")
        elif (
            lines and lines[-1] and not (line.startswith(("|", "[^")) or lines[-1].startswith("|"))
        ):
            lines[-1] = f"{lines[-1]} {line}"
        else:
            lines.append(line)
    return "\n".join(line for line in lines if line)


def read_handwritten(directory: Path) -> Iterator[tuple[Chunk, dict[str, Any] | None]]:
    """Yield ``(chunk, canary)`` for every hand-written document (sorted by file name)."""
    for path in sorted(directory.glob("*.md")):
        found = _FRONT.match(path.read_text(encoding="utf-8"))
        if found is None:
            msg = f"{path.name}: missing front matter"
            raise ValueError(msg)
        meta = yaml.safe_load(found.group(1))
        chunk = Chunk(
            chunk_id=ChunkId(f"{meta['doc_id']}#0"),
            doc_id=DocId(meta["doc_id"]),
            tenant=TenantId(meta["tenant"]),
            lang=Lang(meta.get("lang", "de")),
            text=_unwrap(found.group(2)),
            citation_key=None,
            section=None,
            parallel_id=None,
            version_date=None,
            license=SYNTHETIC_LICENSE,
            source="synthetic:handwritten",
            is_attack=bool(meta.get("is_attack", False)),
        )
        canary = meta.get("canary")
        yield (
            chunk,
            ({"tenant": chunk.tenant, "doc_id": chunk.doc_id, **canary} if canary else None),
        )


def _dump(rows: Sequence[dict[str, Any]]) -> bytes:
    lines = (json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for r in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_slice(raw: Path, out: Path, handwritten: Path = HANDWRITTEN) -> dict[str, Any]:
    """Write the slice corpus to ``out`` and return the manifest as a dict.

    Args:
        raw: ``data/raw`` with the pinned GII archives and EUR-Lex files (``sources.yaml`` beside).
        out: Output directory (created).
        handwritten: Directory of the synthetic documents.

    Returns:
        The manifest (also written as ``manifest.json``).

    Raises:
        ValueError: A hand-written document has no front matter.
    """
    pins = _pins(raw.parent / "sources.yaml")
    used = {pick[1] for pick in GII_PICK.values()} | {f"eurlex:{CELEX}"}
    pin_date = max(str(pins[source]["pinned"]) for source in used)
    by_tenant: dict[str, list[Chunk]] = {t: [] for t in TENANTS}
    for chunk in [*_gii_chunks(raw), *_dsgvo_chunks(raw, pin_date)]:
        by_tenant[chunk.tenant].append(chunk)
    canaries: list[dict[str, Any]] = []
    for chunk, canary in read_handwritten(handwritten):
        by_tenant[chunk.tenant].append(chunk)
        if canary:
            canaries.append(canary)
    out.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    for tenant, chunks in by_tenant.items():
        data = _dump([c.model_dump(mode="json") for c in chunks])
        (out / f"{tenant}.chunks.jsonl").write_bytes(data)
        digests[f"{tenant}.chunks.jsonl"] = hashlib.sha256(data).hexdigest()
    short = hashlib.sha256("".join(digests[k] for k in sorted(digests)).encode()).hexdigest()[:8]
    manifest = {
        "corpus_version": f"slice-{pin_date}.{short}",
        "created_at": f"{pin_date}T00:00:00Z",
        "sources": {
            **{s: str(pins[s]["pinned"]) for s in sorted(used)},
            "handwritten": "synthetic",
        },
        "tenants": {t: len(c) for t, c in by_tenant.items()},
        "sha256": digests,
    }
    (out / "manifest.json").write_bytes(_dump([manifest]).replace(b"\n", b"") + b"\n")
    registry = {"canaries": [_canary(c) for c in canaries]}
    (out / "canaries.public.json").write_bytes(_dump([registry]).replace(b"\n", b"") + b"\n")
    return manifest


def _canary(raw: dict[str, Any]) -> dict[str, Any]:
    keys = ("token", "tenant", "doc_id", "kind", "fact", "probe_question", "forbidden_answer")
    return {k: raw.get(k) for k in keys}


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry: ``build_slice.py [--raw data/raw] [--out corpus/slice_v1]``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--out", type=Path, default=ROOT / "corpus" / "slice_v1")
    args = parser.parse_args(argv)
    manifest = build_slice(args.raw, args.out)
    print(f"{manifest['corpus_version']}: {manifest['tenants']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
