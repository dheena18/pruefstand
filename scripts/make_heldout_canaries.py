"""Build the held-out canary set from the approved private documents (T2.6 S7).

    HELDOUT_SEED=<secret integer> make heldout-canaries

Writes ``datasets/private/heldout/docs/*.md`` (6 documents, 2 per customer tenant, token already
planted) and ``canaries_heldout.json``. The folder is git-ignored and must stay out of the public
repository: copy it by hand to the private executor repo (``canaries/heldout/``) and keep the
seed there as a secret (``docs/ops/secrets.md``). The registry is read only by the trusted gate
process (round 9 X2.5). The seed is read from the environment variable named by ``--seed-env``
and is never printed. Exit codes: 0 done, 2 refused (seed, output location, sources).
"""

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from pruefstand.attacks.heldout import build_heldout
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.ingest.private_docs import PrivateDocFront, PrivateDocsLoader, render_private_doc

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "datasets" / "private" / "heldout"
DEFAULT_SOURCE = REPO / "datasets" / "private_docs"
PUBLIC_GLOBS = ("corpus/*/canaries.public.json", "datasets/canaries/*/canaries.json")
REGISTRY_FILE = "canaries_heldout.json"


def _seed(name: str) -> int:
    raw = os.environ.get(name, "")
    if not raw.isascii() or not raw.isdigit():
        msg = f"environment variable {name} must hold a non-negative integer (the held-out seed)"
        raise DatasetError(msg)
    return int(raw)


def _git(args: list[str], cwd: Path) -> int:
    try:
        return subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True).returncode  # noqa: S603, S607
    except OSError:
        return 128


def _check_location(out: Path, *, allow_tracked: bool) -> None:
    """Refuse an output folder that is inside a git work tree and not ignored by it."""
    anchor = out
    while not anchor.exists():
        anchor = anchor.parent
    if allow_tracked or _git(["rev-parse", "--is-inside-work-tree"], anchor) != 0:
        return
    if _git(["check-ignore", "-q", str(out / REGISTRY_FILE)], anchor) != 0:
        msg = (
            "the output folder is inside a git work tree and not git-ignored "
            "(--allow-tracked: only in the private repo)"
        )
        raise DatasetError(msg)


def _public_tokens(extra: Sequence[Path]) -> set[str]:
    files = [p for pattern in PUBLIC_GLOBS for p in sorted(REPO.glob(pattern))] + list(extra)
    tokens: set[str] = set()
    for path in files:
        try:
            registry = CanaryRegistry.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            msg = f"cannot read the public registry {path.name} ({type(exc).__name__})"
            raise DatasetError(msg) from exc
        tokens.update(c.token for c in registry.canaries)
    return tokens


def main(argv: Sequence[str] | None = None) -> int:
    """Build and write the held-out set; returns the exit code."""
    parser = argparse.ArgumentParser(description="Build the held-out canary set.")
    parser.add_argument("--seed-env", default="HELDOUT_SEED")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--public-registry", type=Path, action="append", default=[])
    parser.add_argument("--allow-tracked", action="store_true")
    args = parser.parse_args(argv)
    try:
        seed = _seed(args.seed_env)
        _check_location(args.out, allow_tracked=args.allow_tracked)
        sources = list(PrivateDocsLoader().load(args.source))
        docs, registry = build_heldout(sources, seed, _public_tokens(args.public_registry))
    except DatasetError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    folder = args.out / "docs"
    folder.mkdir(parents=True, exist_ok=True)
    for stale in folder.glob("*.md"):
        stale.unlink()
    semantic = {c.doc_id: c for c in registry.canaries if c.kind == "semantic"}
    for doc in docs:
        canary = semantic[doc.doc_id]
        front = PrivateDocFront(
            doc_id=doc.doc_id, tenant=doc.tenant, title=doc.title,
            semantic_fact=str(canary.fact), semantic_value=canary.token,
            probe_question=str(canary.probe_question),
            forbidden_answer=str(canary.forbidden_answer),
        )  # fmt: skip
        (folder / f"{doc.doc_id}.md").write_text(
            render_private_doc(front, doc.text), encoding="utf-8"
        )
    (args.out / REGISTRY_FILE).write_text(registry.model_dump_json() + "\n", encoding="utf-8")
    print(f"held-out set: documents={len(docs)} canaries={len(registry.canaries)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
