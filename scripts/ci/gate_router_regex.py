"""The rules ``gate-router.yml`` inlines (T6.2b S1b, X2.2, P4.2, D1022), generated once.

``gate-router.yml`` cannot read repository files (no checkout of any ref), so the gated-path list
(``gated_paths.txt``, the ci-cd.md §5 list) and the release-exempt rules are inlined in the workflow
as environment values. This module generates them and holds the reference decision
(:func:`classify`) that the workflow's script mirrors; the tests compare the workflow with both.

Usage: ``python scripts/ci/gate_router_regex.py`` prints the two values for the workflow.
"""

import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATED_PATHS = ROOT / "infra/gate-executor/orchestrator/gate_orchestrator/gated_paths.txt"
RELEASE_AUTHOR = "pruefstand-release[bot]"
RELEASE_BRANCH = "release-please--"
NOT_GATED = "not gated (no gated paths changed)"
RELEASE_BUMP = "not gated (release version bump)"
AWAITING = "gated: awaiting tier-2 dispatch"
# ci-cd.md §5 "Release exemption": file -> the only changed-line shape allowed (without +/-)
RELEASE_RULES: tuple[dict[str, object], ...] = (
    {"file": r"^(?:.+/)?pyproject\.toml$", "line": r'^version = "[^"]+"$'},
    {"file": r"^\.release-please-manifest\.json$", "line": r'^\s*"[^"]+": "[^"]+",?$'},
    {"file": r"^action/action\.yml$", "line": r"^\s*image: \S+$"},
    {"file": r"^CHANGELOG\.md$", "line": r"^.*$"},
    {
        "file": r"^uv\.lock$",
        "line": r'^version = "[^"]+"$',
        "after_name": ["pruefstand", "rag-demo"],  # the two workspace members only (X2.9)
    },
)
_NAME = re.compile(r'^name = "([^"]+)"$')


def load_patterns(path: Path = GATED_PATHS) -> list[str]:
    """The gated-path globs (``dir/**`` or an exact path), one per line."""
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def gated_regex(patterns: Iterable[str]) -> str:
    r"""One anchored regex for the globs: ``dir/**`` = anything below ``dir/``, else the exact path.

    >>> gated_regex(["apps/rag-demo/**", "uv.lock"])
    '^(?:apps/rag\\-demo/.+|uv\\.lock)$'
    """
    alts = [re.escape(p[:-3]) + "/.+" if p.endswith("/**") else re.escape(p) for p in patterns]
    return "^(?:" + "|".join(alts) + ")$"


def release_rules_json() -> str:
    """The release-exempt rules as compact JSON (the workflow's ``RELEASE_RULES``)."""
    return json.dumps(RELEASE_RULES, separators=(",", ":"))


def _line_exempt(patch: str, rule: Mapping[str, object]) -> bool:
    line_re = re.compile(str(rule["line"]))
    names = rule.get("after_name")
    current = ""
    for raw in patch.splitlines():
        if raw.startswith(("+++", "---", "@@")):
            continue
        body = raw[1:]
        found = _NAME.match(body)
        if found:
            current = found.group(1)
        if raw[:1] not in "+-":
            continue
        if not line_re.match(body):
            return False
        if isinstance(names, list) and current not in names:
            return False
    return True


def _file_exempt(item: Mapping[str, object], rules: Sequence[Mapping[str, object]]) -> bool:
    name, patch = str(item.get("filename", "")), item.get("patch")
    if not isinstance(patch, str):
        return False  # no patch (binary, too large): never exempt (fail closed)
    rule = next((r for r in rules if re.match(str(r["file"]), name)), None)
    return rule is not None and _line_exempt(patch, rule)


def classify(
    files: Sequence[Mapping[str, object]],
    *,
    author: str,
    head_ref: str,
    gated: str,
    rules: Sequence[Mapping[str, object]] = RELEASE_RULES,
) -> tuple[str, str]:
    """``(state, description)`` that ``gate-router.yml`` posts as ``pruefstand/gate``.

    Args:
        files: ``pulls/{n}/files`` entries (``filename``, ``patch``).
        author: the PR author's login.
        head_ref: the PR's head branch name.
        gated: :func:`gated_regex` of the gated paths.
        rules: the release-exempt rules.

    Returns:
        ``("success", NOT_GATED)``, ``("success", RELEASE_BUMP)`` or ``("pending", AWAITING)``.
    """
    gated_re = re.compile(gated)
    if not any(gated_re.match(str(f.get("filename", ""))) for f in files):
        return "success", NOT_GATED
    release_pr = author == RELEASE_AUTHOR and head_ref.startswith(RELEASE_BRANCH)
    if release_pr and files and all(_file_exempt(f, rules) for f in files):
        return "success", RELEASE_BUMP
    return "pending", AWAITING


def main() -> int:
    """Print ``GATED_RE`` and ``RELEASE_RULES`` for ``.github/workflows/gate-router.yml``."""
    print(f"GATED_RE: '{gated_regex(load_patterns())}'")
    print(f"RELEASE_RULES: '{release_rules_json()}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
