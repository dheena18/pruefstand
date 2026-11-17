"""T9.1a: the files a release PR changes are exactly the release-exempt ones (D105, X2.9, D1292).

release-please changes the root ``pyproject.toml`` (``release-type: python``), its ``extra-files``,
``.release-please-manifest.json`` and ``CHANGELOG.md``; the ``uv lock`` step changes the members'
version lines in ``uv.lock``. Every one of them must have a rule in ``RELEASE_RULES`` (the rules
``gate-router.yml`` inlines), and the lock members must equal the lock guard's.
"""

import json
import re
from pathlib import Path

from ci.check_release_lock_diff import MEMBERS
from ci.gate_router_regex import RELEASE_RULES

ROOT = Path(__file__).resolve().parents[2]


def release_files() -> list[str]:
    cfg = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    extra = [str(e["path"]) for e in cfg["packages"]["."]["extra-files"]]
    return ["pyproject.toml", *extra, ".release-please-manifest.json", "CHANGELOG.md", "uv.lock"]


def test_every_file_a_release_pr_changes_has_an_exemption_rule() -> None:
    for path in release_files():
        assert any(re.match(str(r["file"]), path) for r in RELEASE_RULES), path


def test_the_version_strings_are_exempt_lines() -> None:
    pyproject = next(r for r in RELEASE_RULES if re.match(str(r["file"]), "pyproject.toml"))
    assert re.match(str(pyproject["line"]), 'version = "0.2.0"')
    assert not re.match(str(pyproject["line"]), 'requires-python = ">=3.12"')


def test_the_lock_members_equal_the_guard_and_ci_cd_md() -> None:
    lock = next(r for r in RELEASE_RULES if r["file"] == r"^uv\.lock$")
    names = lock["after_name"]
    assert isinstance(names, list)
    assert set(names) == set(MEMBERS) == {"pruefstand", "rag-demo", "pruefstand-workspace"}
    text = (ROOT / "docs/engineering/ci-cd.md").read_text(encoding="utf-8")
    assert all(f"`{m}`" in text for m in MEMBERS)
