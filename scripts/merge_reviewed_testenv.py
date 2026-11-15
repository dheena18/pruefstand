"""Test support for ``scripts/tests/test_merge_reviewed.py``: fake ``gh``, git sandbox, fixtures.

The fake ``gh`` is a shell tool stand-in on PATH (not a model or target fake, CLAUDE.md
section 6). It serves recorded-shape GitHub JSON fixtures through the real ``jq`` for the
``--jq`` projections the script uses, and logs merge and comment calls. Git is real: each test
gets a bare ``origin`` with ``main``, a clone that runs the script, and a PR branch pushed to
``origin``.
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = "dheena18/pruefstand"
REQUIRED = ("check", "scan", "images-gate", "docs-gate", "ui-check")
WORKFLOW = {
    "check": "ci.yml",
    "scan": "security.yml",
    "images-gate": "build-images.yml",
    "docs-gate": "docs.yml",
    "ui-check": "ui.yml",
}
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}
SEED_FILES = {
    "docs/a.md": "a\n",
    "infra/vm/setup.sh": "echo vm\n",
    "docs/ops/secrets.md": "secrets\n",
    ".claude/settings.json": "{}\n",
    ".github/workflows/ci.yml": "name: ci\n",
}

FAKE_GH = """#!/usr/bin/env bash
d="$FAKE_DIR"
echo "$*" >> "$d/calls.log"
jqexpr=""; args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  [ "${args[$i]}" = "--jq" ] && jqexpr="${args[$((i + 1))]}"
done
out() { [ -f "$1" ] || { echo "HTTP 404" >&2; exit 1; }
        if [ -n "$jqexpr" ]; then jq -r "$jqexpr" "$1"; else cat "$1"; fi; }
case "$1 $2" in
  "pr view")
    n=$(cat "$d/viewcount" 2>/dev/null || echo 0); echo $((n + 1)) > "$d/viewcount"
    f="$d/pr.json"; if [ "$n" -ge 1 ] && [ -f "$d/pr2.json" ]; then f="$d/pr2.json"; fi
    out "$f"; exit 0 ;;
  "pr merge") [ -f "$d/merge_fails" ] && exit 1; exit 0 ;;
  "pr comment") exit 0 ;;
esac
[ "$1" = api ] || exit 9
case "$2" in
  */rules/branches/main) out "$d/rules.json" ;;
  */check-runs*) out "$d/checkruns.json" ;;
  */statuses*) out "$d/statuses.json" ;;
  */actions/jobs/*) out "$d/jobs/${2##*/}.json" ;;
  */actions/runs/*) out "$d/runs/${2##*/}.json" ;;
  *) exit 9 ;;
esac
"""


def git(cwd: Path, *args: str) -> str:
    """Run git in cwd (fixed identity) and return its stripped stdout."""
    env = {**os.environ, **GIT_ENV}
    res = subprocess.run(  # noqa: S603  # fixed argv
        ["git", *args],  # noqa: S607  # git from PATH in tests
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return res.stdout.strip()


def write_json(path: Path, obj: object) -> None:
    """Write obj as JSON to path, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def make_template(root: Path) -> Path:
    """Build a bare ``origin.git`` under ``root`` holding ``main`` with the real scripts."""
    seed = root / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    (seed / "scripts").mkdir()
    for name in ("merge_reviewed.sh", "merge_paths.py"):
        shutil.copy2(SCRIPTS / name, seed / "scripts" / name)
    for rel, text in SEED_FILES.items():
        (seed / rel).parent.mkdir(parents=True, exist_ok=True)
        (seed / rel).write_text(text, encoding="utf-8")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "seed")
    origin = root / "origin.git"
    git(root, "clone", "-q", "--bare", str(seed), str(origin))
    git(origin, "config", "uploadpack.allowAnySHA1InWant", "true")
    return origin


class Env:
    """One sandbox: fake gh, bare origin, the checkout that runs the script, a PR author clone."""

    def __init__(self, root: Path, template: Path) -> None:
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        self.home = root / "home"
        self.home.mkdir()
        self.fake = root / "fake"
        self.fake.mkdir()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        self.origin = root / "origin.git"
        shutil.copytree(template, self.origin)
        self.work = root / "work"
        git(root, "clone", "-q", str(self.origin), str(self.work))
        self.author = root / "author"
        git(root, "clone", "-q", str(self.origin), str(self.author))
        self.sha = ""
        self.pr_number = 7

    @property
    def script(self) -> Path:
        """Path of the script under test inside the work checkout."""
        return self.work / "scripts" / "merge_reviewed.sh"

    def pr(self, changes: dict[str, str | None] | None = None) -> str:
        """Commit ``changes`` (None deletes) on a PR branch, push it, set up fixtures."""
        changes = changes or {"docs/a.md": "changed\n"}
        git(self.author, "checkout", "-q", "-b", "pr", "main")
        for rel, text in changes.items():
            target = self.author / rel
            if text is None:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
        git(self.author, "add", "-A")
        git(self.author, "commit", "-q", "-m", "pr")
        git(self.author, "push", "-q", "origin", "pr")
        self.sha = git(self.author, "rev-parse", "HEAD")
        self.fixtures()
        return self.sha

    def fixtures(self) -> None:
        """Write the GitHub JSON fixtures for the current PR head."""
        sha = self.sha
        write_json(
            self.fake / "pr.json",
            {"baseRefName": "main", "state": "OPEN", "isDraft": False, "headRefOid": sha},
        )
        runs = []
        for i, name in enumerate(REQUIRED):
            runs.append(
                {
                    "id": 100 + i,
                    "name": name,
                    "status": "completed",
                    "conclusion": "success",
                    "app": {"slug": "github-actions"},
                }
            )
            write_json(
                self.fake / "jobs" / f"{100 + i}.json",
                {"run_id": 200 + i, "name": name, "head_sha": sha},
            )
            write_json(
                self.fake / "runs" / f"{200 + i}.json",
                {
                    "event": "pull_request",
                    "head_sha": sha,
                    "path": f".github/workflows/{WORKFLOW[name]}",
                    "repository": {"full_name": REPO},
                    "head_repository": {"full_name": REPO},
                },
            )
        write_json(self.fake / "checkruns.json", {"check_runs": runs})
        self.set_rules(list(REQUIRED))
        self.set_gate("success", "pruefstand-bot[bot]")

    def set_rules(self, contexts: list[str]) -> None:
        """Set the required contexts the fake ruleset lists."""
        rule = {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": c} for c in contexts]},
        }
        write_json(self.fake / "rules.json", [{"type": "pull_request"}, rule])

    def set_gate(self, state: str, creator: str) -> None:
        """Set the newest `pruefstand/gate` commit status."""
        write_json(
            self.fake / "statuses.json",
            [{"context": "pruefstand/gate", "state": state, "creator": {"login": creator}}],
        )

    def patch(self, rel: str, **fields: object) -> None:
        """Merge ``fields`` into the fixture JSON file ``rel``."""
        path = self.fake / rel
        obj = json.loads(path.read_text(encoding="utf-8"))
        obj.update(fields)
        write_json(path, obj)

    def run(
        self, *args: str, verdict: str | None = None, home: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run the script in the work checkout with the fake gh first on PATH."""
        env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "FAKE_DIR": str(self.fake),
            "HOME": str(home or self.home),
        }
        if verdict is not None:
            env["REVIEW_VERDICT"] = verdict
        return subprocess.run(  # noqa: S603  # fixed argv
            [str(self.script), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=120,
        )

    def calls(self) -> str:
        """Return the log of fake gh calls."""
        log = self.fake / "calls.log"
        return log.read_text(encoding="utf-8") if log.exists() else ""

    def merged(self) -> bool:
        """Return True when the script called ``gh pr merge``."""
        return "pr merge" in self.calls()
