"""gate-router.yml (T6.2b S1b, D1022): inlined rules = generator; Python and JS agree."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from ci.gate_router_regex import (
    AWAITING,
    NOT_GATED,
    RELEASE_BUMP,
    classify,
    gated_regex,
    load_patterns,
    release_rules_json,
)

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/gate-router.yml"
DOC: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
STEPS = DOC["jobs"]["route"]["steps"]
CLASSIFY = next(s for s in STEPS if s.get("id") == "classify")
GATED = gated_regex(load_patterns())
RELEASE = "pruefstand-release[bot]"
REF = "release-please--branches--main"

PYPROJECT = "\n".join(
    [
        "@@ -1,3 +1,3 @@",
        " [project]",
        ' name = "rag-demo"',
        '-version = "0.1.0"',
        '+version = "0.2.0"',
    ]
)


def _lock_hunk(name: str, old: str, new: str) -> str:
    lines = ["@@ -1,3 +1,3 @@", " [[package]]", f' name = "{name}"']
    return "\n".join([*lines, f'-version = "{old}"', f'+version = "{new}"'])


UV_MEMBERS = (
    _lock_hunk("pruefstand", "0.1.0", "0.2.0") + "\n" + _lock_hunk("rag-demo", "0.1.0", "0.2.0")
)
UV_OTHER = _lock_hunk("httpx", "0.27.0", "0.28.0")
CHANGELOG = "@@ -1,1 +1,3 @@\n+## 0.2.0\n+- feat: x\n # Changelog"
RELEASE_FILES = [
    {"filename": "apps/rag-demo/pyproject.toml", "patch": PYPROJECT},
    {"filename": "uv.lock", "patch": UV_MEMBERS},
    {"filename": "CHANGELOG.md", "patch": CHANGELOG},
]
OTHER_LOCK = {"filename": "uv.lock", "patch": UV_OTHER}
SRC = {"filename": "apps/rag-demo/src/x.py", "patch": "+x = 1"}
GATE = ("pending", AWAITING)
CASES: list[tuple[str, list[dict[str, Any]], str, str, tuple[str, str]]] = [
    (
        "docs-only",
        [{"filename": "docs/x.md", "patch": "+x"}],
        "a",
        "feat/x",
        ("success", NOT_GATED),
    ),
    ("release", RELEASE_FILES, RELEASE, REF, ("success", RELEASE_BUMP)),
    ("release+other-lock-line", [*RELEASE_FILES, OTHER_LOCK], RELEASE, REF, GATE),
    ("release+src", [*RELEASE_FILES, SRC], RELEASE, REF, GATE),
    ("release-diff-other-author", RELEASE_FILES, "someone", REF, GATE),
    ("release-author-other-branch", RELEASE_FILES, RELEASE, "feat/x", GATE),
    ("lock-without-patch", [{"filename": "uv.lock"}], RELEASE, REF, GATE),
    ("gated-src", [SRC], "someone", "feat/x", GATE),
]
IDS = [c[0] for c in CASES]


def test_workflow_inlines_exactly_the_generated_rules() -> None:
    env = CLASSIFY["env"]
    assert env["GATED_RE"] == GATED
    assert env["RELEASE_RULES"] == release_rules_json()


@pytest.mark.parametrize(
    "path",
    [
        "apps/rag-demo/src/x.py",
        "apps/rag-demo/configs/rag.gpu.yaml",
        "uv.lock",
        "pyproject.toml",
        "infra/gpu/models.yaml",
        "packages/pruefstand/src/pruefstand/gate/stats.py",
        "datasets/x/v1/core.jsonl",
    ],
)
def test_gated_paths_match(path: str) -> None:
    assert classify([{"filename": path, "patch": "+x"}], author="a", head_ref="b", gated=GATED)[
        0
    ] == ("pending")


@pytest.mark.parametrize(
    "path",
    [
        "docs/x.md",
        "packages/pruefstand/pyproject.toml",
        "packages/pruefstand/src/pruefstand/report/x.py",
        ".github/workflows/x.yml",
        "apps/dashboard/x.ts",
        "apps/rag-demo-old/x.py",
        "xuv.lock",
    ],
)
def test_other_paths_do_not_match(path: str) -> None:
    files = [{"filename": path, "patch": "+x"}]
    assert classify(files, author="a", head_ref="b", gated=GATED) == ("success", NOT_GATED)


@pytest.mark.parametrize(
    ("name", "files", "author", "ref", "expected"), CASES, ids=[c[0] for c in CASES]
)
def test_python_decision(
    name: str, files: list[dict[str, Any]], author: str, ref: str, expected: tuple[str, str]
) -> None:
    assert classify(files, author=author, head_ref=ref, gated=GATED) == expected


HARNESS = """
const script = require('fs').readFileSync(process.argv[2], 'utf8');
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = {};
const core = { setOutput: (k, v) => { out[k] = v; } };
const github = { paginate: async () => input.files, rest: { pulls: { listFiles: null } } };
const context = { repo: { owner: 'o', repo: 'r' }, payload: { pull_request: input.pr } };
const fn = new (Object.getPrototypeOf(async function () {}).constructor)(
  'github', 'context', 'core', 'process', script);
fn(github, context, core, { env: input.env }).then(() => console.log(JSON.stringify(out)));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize(
    ("name", "files", "author", "ref", "expected"), CASES, ids=[c[0] for c in CASES]
)
def test_workflow_script_decides_like_python(  # noqa: PLR0917 - parametrized table
    tmp_path: Path, name: str, files: list[dict[str, Any]], author: str, ref: str,
    expected: tuple[str, str],
) -> None:  # fmt: skip
    script = tmp_path / "classify.js"
    script.write_text(CLASSIFY["with"]["script"], encoding="utf-8")
    harness = tmp_path / "harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    payload = {
        "files": files,
        "pr": {"number": 7, "user": {"login": author}, "head": {"ref": ref, "sha": "a" * 40}},
        "env": CLASSIFY["env"],
    }
    done = subprocess.run(  # noqa: S603 - fixed argv
        [shutil.which("node") or "node", str(harness), str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(done.stdout)
    assert (out["state"], out["description"]) == expected


def test_status_step_uses_the_app_token_and_never_overwrites_a_result() -> None:
    post = STEPS[-1]
    assert post["with"]["github-token"] == "${{ steps.app.outputs.token }}"
    assert "getCombinedStatusForRef" in post["with"]["script"]
    assert "current.state !== 'pending'" in post["with"]["script"]
    app = next(s for s in STEPS if s.get("id") == "app")
    assert app["uses"].startswith("actions/create-github-app-token@")
    assert app["with"]["permission-statuses"] == "write"


def test_no_pr_text_is_interpolated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for field in ("title", "body", "head.ref", "head.label"):
        assert f"github.event.pull_request.{field}" not in text
