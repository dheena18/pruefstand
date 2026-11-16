"""Apply or revert one mutation entry on a temporary git worktree (T7.1a S2, S5).

Usage::

    uv run python benchmarks/mutations/apply.py apply M08 --worktree /tmp/m08
    uv run python benchmarks/mutations/apply.py revert M08 --worktree /tmp/m08

``apply`` creates the worktree with ``git worktree add --detach`` at ``base_sha`` when it does not
exist and refuses any directory it did not create, so the user's own checkout is never touched.
``rag_overrides`` are merged into ``apps/rag-demo/configs/rag.gpu.yaml`` (the tier-2 profile,
X3.15) and, for ``tier1: true`` entries, into the tier-1 ``rag.yaml``; ``patch`` is applied with
``git apply``. Leak mutations (M08, M09) run with the held-out canary set; ``--canary-set
published`` is refused unless ``--allow-published`` is given (canary hygiene, X2.5).
"""

import argparse
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import yaml
from pydantic import JsonValue

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script: import mutations.*

from mutations.schema import MUTATIONS_ROOT, MutationSpec, load_index, load_spec

from pruefstand.core.errors import PruefstandError

REPO = MUTATIONS_ROOT.parents[1]
GPU_CONFIG = "apps/rag-demo/configs/rag.gpu.yaml"
LIVE_CONFIG = "apps/rag-demo/configs/rag.yaml"
GIT_TIMEOUT_S = 120
MARKER = "pruefstand-mutation-worktree"
CanarySet = Literal["heldout", "published"]


class MutationError(PruefstandError):
    """A mutation cannot be applied or reverted."""


def check_canary_set(spec: MutationSpec, canary_set: CanarySet, *, allow_published: bool) -> None:
    """Refuse the published canary set for a leak mutation unless explicitly allowed.

    Raises:
        MutationError: ``spec`` is a leak mutation, ``canary_set`` is ``published`` and
            ``allow_published`` is false.
    """
    if spec.is_leak and canary_set == "published" and not allow_published:
        msg = f"{spec.id} is a leak mutation: use --canary-set heldout or pass --allow-published"
        raise MutationError(msg)


def merge_overrides(
    base: Mapping[str, JsonValue], overrides: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    """Deep-merge ``overrides`` into ``base`` (nested mappings merge, everything else replaces).

    Examples:
        >>> merge_overrides({"top_k": 8, "analyzer": {"compound_split": True, "stemmer": "x"}},
        ...                 {"analyzer": {"compound_split": False}})
        {'top_k': 8, 'analyzer': {'compound_split': False, 'stemmer': 'x'}}
    """
    merged = dict(base)
    for key, value in overrides.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = merge_overrides(current, value)
        else:
            merged[key] = value
    return merged


def _git(*args: str, cwd: Path) -> str:
    try:
        done = subprocess.run(  # noqa: S603  (fixed git argv, no shell)
            ["git", *args],  # noqa: S607  (git from PATH, like every repo script)
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        msg = f"git {' '.join(args)} failed in {cwd}: {getattr(exc, 'stderr', '') or exc}"
        raise MutationError(msg) from exc
    return done.stdout


def ensure_worktree(worktree: Path, ref: str, repo: Path = REPO) -> None:
    """Create ``worktree`` at ``ref`` if missing; refuse any directory this tool did not create.

    A worktree made here carries the marker file ``MARKER`` in its own git directory (outside the
    working tree, so ``git status`` stays clean). An existing directory without the marker (the
    user's checkout, another agent's worktree, any other path) is refused.

    Raises:
        MutationError: ``worktree`` exists without the marker, or git fails.
    """
    if not worktree.exists():
        _git("worktree", "add", "--detach", "--quiet", str(worktree), ref, cwd=repo)
        _marker(worktree).write_text("created by benchmarks/mutations/apply.py\n", encoding="utf-8")
    elif not (worktree / ".git").is_file() or not _marker(worktree).is_file():
        msg = f"{worktree} was not created by apply.py (no {MARKER}): refusing to mutate it"
        raise MutationError(msg)


def _marker(worktree: Path) -> Path:
    return Path(_git("rev-parse", "--absolute-git-dir", cwd=worktree).strip()) / MARKER


def _scalar(value: JsonValue) -> str:
    return yaml.safe_dump(value, default_flow_style=True).removesuffix("...\n").strip()


def render_overrides(text: str, overrides: Mapping[str, JsonValue]) -> str:
    r"""Return the YAML ``text`` with ``overrides`` deep-merged into it.

    Top-level scalar overrides of keys the file already has replace that one line, so comments and
    layout survive and the diff is one line per key (like ``configs/bugs/gpu/*.yaml``). Anything
    else (nested or new keys) re-dumps the merged mapping.

    Examples:
        >>> print(render_overrides("# tier 2\ntop_k: 8  # default\nreranker: 'on'\n", {"top_k": 3}))
        # tier 2
        top_k: 3
        reranker: 'on'
        <BLANKLINE>
    """
    merged = merge_overrides(yaml.safe_load(text), overrides)
    lines = text.splitlines(keepends=True)
    for key, value in overrides.items():
        hits = [i for i, old in enumerate(lines) if old.startswith(f"{key}:")]
        if isinstance(value, Mapping) or len(hits) != 1:
            break
        lines[hits[0]] = f"{key}: {_scalar(value)}\n"
    else:
        rendered = "".join(lines)
        if yaml.safe_load(rendered) == merged:
            return rendered
    return yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)


def _apply_overrides(spec: MutationSpec, worktree: Path) -> None:
    assert spec.rag_overrides is not None  # noqa: S101  (guaranteed by MutationSpec)
    files = [GPU_CONFIG, LIVE_CONFIG] if spec.tier1 else [GPU_CONFIG]
    for rel in files:
        path = worktree / rel
        text = render_overrides(path.read_text(encoding="utf-8"), spec.rag_overrides)
        path.write_text(text, encoding="utf-8")


def check_pristine(worktree: Path, ref: str) -> None:
    """Refuse a worktree whose HEAD is not ``ref`` or that has any change (tracked or untracked).

    Raises:
        MutationError: HEAD differs from ``ref``, or ``git status --porcelain`` is not empty.
    """
    base = _git("rev-parse", "--verify", f"{ref}^{{commit}}", cwd=worktree).strip()
    head = _git("rev-parse", "HEAD", cwd=worktree).strip()
    if head != base:
        msg = f"{worktree} is at {head[:12]}, not at the base {base[:12]}: use a fresh worktree"
        raise MutationError(msg)
    if _git("status", "--porcelain", "--untracked-files=all", cwd=worktree).strip():
        msg = f"{worktree} is not clean (a mutation is applied?): run revert first"
        raise MutationError(msg)


def apply_mutation(
    spec: MutationSpec, worktree: Path, ref: str, root: Path = MUTATIONS_ROOT
) -> None:
    """Apply ``spec`` to ``worktree`` (created at ``ref`` when missing).

    An existing worktree must still be at ``ref`` and clean, so mutations never stack and never
    run on another base; ``revert`` cleans it, a moved HEAD needs a fresh worktree.

    Raises:
        MutationError: the worktree was not created by this tool, is not at ``ref``, is not clean,
            or ``git apply`` fails.
    """
    ensure_worktree(worktree, ref)
    check_pristine(worktree, ref)
    if spec.patch is not None:
        _git("apply", str((root / spec.id / spec.patch).resolve()), cwd=worktree)
    else:
        _apply_overrides(spec, worktree)


def revert(worktree: Path) -> None:
    """Undo every change in ``worktree`` (tracked and untracked); ``git status`` is clean after.

    Raises:
        MutationError: ``worktree`` is missing or was not created by this tool, or git fails.
    """
    if not worktree.exists():
        msg = f"{worktree} does not exist: nothing to revert"
        raise MutationError(msg)
    ensure_worktree(worktree, "HEAD")
    _git("reset", "--hard", "--quiet", cwd=worktree)
    _git("clean", "-fdq", cwd=worktree)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the exit code (0 ok, 1 refused or failed)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("action", choices=["apply", "revert"])
    parser.add_argument("entry")
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--canary-set", choices=["heldout", "published"], default="heldout")
    parser.add_argument("--allow-published", action="store_true")
    args = parser.parse_args(argv)
    try:
        pending = load_index().pending
        if args.action == "apply" and args.entry in pending:
            msg = f"{args.entry} is pending, not applied: {pending[args.entry]}"
            raise MutationError(msg)
        spec = load_spec(args.entry)
        if args.action == "revert":
            revert(args.worktree)
            return 0
        check_canary_set(spec, args.canary_set, allow_published=args.allow_published)
        apply_mutation(spec, args.worktree, load_index().base_sha)
    except PruefstandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{spec.id} applied in {args.worktree} (canary set {args.canary_set})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
