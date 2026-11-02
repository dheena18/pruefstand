"""Catalogue lookups for the VM shell scripts (T3.1a): what to load, which JSON bodies to send.

PyYAML only (no pydantic), so the scripts run with the system ``python3`` of the VM. The full
validation is ``catalogue_schema.py`` (tests, CI). Every lookup fails closed: an unknown id or tag
exits 64, and nothing is built by string concatenation in the shells; the bodies come from
``json.dumps`` here.

Commands (``PRUEFSTAND_GPU_CATALOGUE`` overrides the catalogue path):
  mode-set day|night     TSV ``id tag server digest num_ctx role``, generator first (ADR-0019)
  preload-body <tag> [--embed]   ``{"model", "keep_alive", "options"}`` (AI12-04: exactly the
                         catalogue options); --embed: the /api/embed form (``input`` added), the
                         fallback for embedding-only models
  unload-body <tag> [--embed]    ``{"model", "keep_alive": 0}`` (--embed: with ``input``)
  catalogue-tags         every Ollama tag of the catalogue
  lookup <id>            TSV ``tag digest role disk_bytes engine`` of an ``ollama/<tag>`` id
  server <tag>           ``gpu0`` or ``gpu1``: the lane (URL setting) of a tag
  role <tag>             ``generator|judge|embed``
  tag-digest <tag>       reads an ``/api/tags`` body on stdin, prints the digest of the tag
  ps-rows                reads an ``/api/ps`` body on stdin, prints TSV
                         ``name digest context size size_vram``
"""

import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, NoReturn

import yaml

DEFAULT = Path(__file__).resolve().parent / "models.yaml"
TAG_RE = re.compile(r"^[a-z0-9._:/-]+$")
ORDER = {"generator": 0, "embed": 1, "judge": 2}
EXIT_USAGE = 64
Entry = dict[str, Any]


class UsageError(Exception):
    """A fail-closed refusal; ``code`` is the process exit code."""

    def __init__(self, message: str, code: int = EXIT_USAGE) -> None:
        """Keep the message and the exit code."""
        super().__init__(message)
        self.code = code


def _refuse(message: str) -> NoReturn:
    raise UsageError(message)


def entries(path: Path | None = None) -> list[Entry]:
    """The catalogue entries of ``models.yaml`` (or ``PRUEFSTAND_GPU_CATALOGUE``)."""
    chosen = path or Path(os.environ.get("PRUEFSTAND_GPU_CATALOGUE") or DEFAULT)
    data = yaml.safe_load(chosen.read_text(encoding="utf-8"))
    return list(data["models"])


def ollama_entries() -> list[Entry]:
    """Entries served by the Ollama server (not the CPU reranker)."""
    return [e for e in entries() if e["engine"] == "ollama"]


def by_tag(tag: str) -> Entry:
    """The Ollama entry with this bare tag; exit 64 for anything else."""
    if not TAG_RE.match(tag):
        _refuse("invalid model tag")
    for entry in ollama_entries():
        if entry["tag"] == tag:
            return entry
    return _refuse(f"{tag} is not in the catalogue")


def by_id(model_id: str) -> Entry:
    """The entry with this id (``ollama/<tag>`` or ``cpu/...``); exit 64 when unknown."""
    for entry in entries():
        if entry["id"] == model_id:
            return entry
    return _refuse(f"{model_id} is not in the catalogue")


def mode_set(mode: str) -> list[Entry]:
    """The standard models of a mode, generator first; ``datagen`` and anything else is refused."""
    if mode == "datagen":
        _refuse("no datagen mode (ADR-0019)")
    if mode not in {"day", "night"}:
        _refuse(f"unknown mode {mode!r}: use day or night")
    chosen = [e for e in ollama_entries() if e["standard"] and e["role"] in ORDER]
    return sorted(chosen, key=lambda e: ORDER[e["role"]])


def dumps(body: dict[str, Any]) -> str:
    """Compact JSON, deterministic key order of construction."""
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False)


def preload_body(tag: str, *, embed: bool = False) -> str:
    """The load request of a model: model, keep_alive and exactly the catalogue options."""
    entry = by_tag(tag)
    body: dict[str, Any] = {
        "model": tag,
        "keep_alive": entry["keep_alive"],
        "options": entry["options"],
    }
    return dumps({**body, "input": ["."]} if embed else body)


def unload_body(tag: str, *, embed: bool = False) -> str:
    """The unload request of a model: keep_alive 0."""
    by_tag(tag)
    body: dict[str, Any] = {"model": tag, "keep_alive": 0}
    return dumps({**body, "input": ["."]} if embed else body)


def tag_digest(tags_json: str, tag: str) -> str:
    """The digest ``/api/tags`` reports for ``tag`` (empty when the tag is not listed)."""
    for model in json.loads(tags_json).get("models", []):
        if model.get("name") == tag or model.get("model") == tag:
            return str(model.get("digest", ""))
    return ""


def ps_rows(ps_json: str) -> list[tuple[str, str, str, str, str]]:
    """``(name, digest, context_length|-, size, size_vram)`` of every resident model."""
    return [
        (
            str(m.get("name", "")),
            str(m.get("digest", "")),
            str(m.get("context_length", "-")),
            str(m.get("size", 0)),
            str(m.get("size_vram", 0)),
        )
        for m in json.loads(ps_json).get("models", [])
    ]


def _tsv(*cells: object) -> str:
    return "\t".join(str(c) for c in cells)


def _mode_set_lines(arg: str, _opts: frozenset[str]) -> list[str]:
    return [
        _tsv(e["id"], e["tag"], e["server"], e["digest"], e["options"]["num_ctx"], e["role"])
        for e in mode_set(arg)
    ]


def _lookup_line(arg: str, _opts: frozenset[str]) -> list[str]:
    e = by_id(arg)
    return [_tsv(e["tag"], e.get("digest", ""), e["role"], e.get("disk_bytes", 0), e["engine"])]


ONE_ARG: dict[str, Callable[[str, frozenset[str]], list[str]]] = {
    "mode-set": _mode_set_lines,
    "preload-body": lambda arg, opts: [preload_body(arg, embed="--embed" in opts)],
    "unload-body": lambda arg, opts: [unload_body(arg, embed="--embed" in opts)],
    "lookup": _lookup_line,
    "server": lambda arg, _opts: [str(by_tag(arg)["server"])],
    "role": lambda arg, _opts: [str(by_tag(arg)["role"])],
    "tag-digest": lambda arg, _opts: [tag_digest(sys.stdin.read(), arg)],
}
NO_ARG: dict[str, Callable[[], list[str]]] = {
    "catalogue-tags": lambda: [e["tag"] for e in ollama_entries()],
    "ps-rows": lambda: [_tsv(*row) for row in ps_rows(sys.stdin.read())],
}


def run(argv: Sequence[str]) -> list[str]:
    """Execute one command; returns the output lines."""
    if not argv:
        _refuse("usage: gpu_catalogue.py <command> [arg]")
    cmd, args = argv[0], list(argv[1:])
    opts = frozenset(args[1:])
    args = args[:1] if opts <= {"--embed"} else args
    if cmd in NO_ARG and not args:
        return NO_ARG[cmd]()
    if cmd in ONE_ARG and len(args) == 1:
        return ONE_ARG[cmd](args[0], opts)
    return _refuse(f"unknown command or wrong arguments: {cmd}")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; a refusal prints to stderr and returns its exit code."""
    try:
        lines = run(sys.argv[1:] if argv is None else argv)
    except UsageError as err:
        sys.stderr.write(f"gpu_catalogue: {err}\n")
        return err.code
    except (OSError, ValueError, KeyError) as err:
        sys.stderr.write(f"gpu_catalogue: {type(err).__name__}: {err}\n")
        return 1
    sys.stdout.write("".join(f"{line}\n" for line in lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
