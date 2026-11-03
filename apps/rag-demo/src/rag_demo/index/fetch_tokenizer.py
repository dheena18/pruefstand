"""Fetch the embedding model's ``tokenizer.json`` named by the catalogue and verify its sha256.

Run at image build time (``python -m rag_demo.index.fetch_tokenizer --out <file>``) so the
candidate never needs the internet at runtime (DEV11-21), and by ``make fetch-tokenizer``.
"""

import argparse
import hashlib
import os
from collections.abc import Sequence
from pathlib import Path

import httpx

from rag_demo.catalogue import load_catalogue
from rag_demo.errors import ConfigError

HF = "https://huggingface.co"
TIMEOUT_S = 120


def source_url(source: str) -> str:
    """Map a catalogue source ``hf:<org>/<repo>/<file>`` to its Hugging Face download URL.

    Raises:
        ConfigError: The source is not of that form.

    Examples:
        >>> source_url("hf:BAAI/bge-m3/tokenizer.json")
        'https://huggingface.co/BAAI/bge-m3/resolve/main/tokenizer.json'
    """
    prefix, _, rest = source.partition(":")
    parts = rest.split("/")
    if prefix != "hf" or len(parts) < 3:
        msg = f"tokenizer source {source!r} must look like hf:<org>/<repo>/<file>"
        raise ConfigError(msg)
    return f"{HF}/{parts[0]}/{parts[1]}/resolve/main/{'/'.join(parts[2:])}"


def verify(data: bytes, sha256: str) -> None:
    """Check ``data`` against the pinned digest.

    Raises:
        ConfigError: The digest differs (the message shows both values).
    """
    actual = hashlib.sha256(data).hexdigest()
    if actual != sha256:
        msg = f"tokenizer sha256 {actual} differs from the catalogue pin {sha256}"
        raise ConfigError(msg)


def fetch(catalogue: Path, entry_id: str, out: Path) -> Path:
    """Download the tokenizer of catalogue entry ``entry_id`` to ``out`` (verified, atomic).

    Raises:
        ConfigError: Unknown entry, no tokenizer pin, bad source or digest mismatch.
    """
    entry = load_catalogue(catalogue).get(entry_id)
    if entry is None or entry.tokenizer is None:
        msg = f"catalogue entry {entry_id!r} has no tokenizer pin"
        raise ConfigError(msg)
    url = source_url(entry.tokenizer.source)
    try:
        resp = httpx.get(url, timeout=TIMEOUT_S, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as err:
        msg = f"cannot download {url}: {type(err).__name__}"
        raise ConfigError(msg) from None
    verify(resp.content, entry.tokenizer.sha256)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    tmp.write_bytes(resp.content)
    tmp.replace(out)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """Command line entry; returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", type=Path, default=os.environ.get("RAG_MODEL_CATALOGUE"))
    parser.add_argument("--id", dest="entry_id", default="ollama/bge-m3")
    parser.add_argument("--out", type=Path, default=os.environ.get("RAG_EMBED_TOKENIZER"))
    args = parser.parse_args(argv)
    if args.catalogue is None or args.out is None:
        parser.error("--catalogue and --out (or RAG_MODEL_CATALOGUE / RAG_EMBED_TOKENIZER) needed")
    out = fetch(Path(args.catalogue), args.entry_id, Path(args.out))
    print(f"tokenizer written to {out}")  # noqa: T201  (command line tool)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
