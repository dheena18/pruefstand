"""T3.1c CPU tests: no tracked file names a real cluster account path (D950)."""

import re
import subprocess

import pytest
from gpu_testkit import GPU_DIR

# --- no real cluster path in tracked files ---

SYNTHETIC = {
    "example", "exuser", "exuserdata", "exuser_models", "zz", "from-file", "other", "a", "x",
    "one", "two", "someone",
    "runs", "cases",  # dashboard URL routes, not a cluster account
}  # fmt: skip
SUBS = r"(?:Models|pruefstand-bin|ollama\.log|start-ollama\.sh)"
PATH_RE = re.compile(rf"(?<![A-Za-z0-9_./-])(?:/data/([A-Za-z0-9_-]+)|~([A-Za-z0-9_-]+)/{SUBS})")


def _real_looking(text: str) -> list[str]:
    """Every ``/data/<name>`` or ``~<name>/Models``-style path whose name is not synthetic."""
    hits = []
    for match in PATH_RE.finditer(text):
        name = match.group(1) or match.group(2)
        if name not in SYNTHETIC:
            hits.append(match.group(0))
    return hits


@pytest.mark.parametrize(
    "template",
    [
        "/data/{n}",
        "x /data/{n}/start-ollama.sh y",
        "~{n}/Models",
        "`/data/{n}/Models`",
        "(/data/{n})",
    ],
)
def test_the_scan_catches_every_shape_of_account_path(template: str) -> None:
    """Mutation test: a bare path, a script path and a ~ path are all caught."""
    assert _real_looking(template.format(n="realuser"))


@pytest.mark.parametrize(
    "text",
    [
        "/data/example/Models",
        "$CLUSTER_DATA_ROOT/Models",
        "/pruefstand/data/runs/x",
        "out/data/cases/1",
    ],
)
def test_the_scan_leaves_synthetic_and_relative_paths_alone(text: str) -> None:
    assert not _real_looking(text)


def test_no_tracked_file_names_a_real_cluster_account_path() -> None:
    top = GPU_DIR.parents[1]
    files = subprocess.run(  # noqa: S603
        ["git", "-C", str(top), "ls-files"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    hits = []
    for name in files:
        path = top / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits += [f"{name}: {h}" for h in _real_looking(text)]
    assert not hits, hits[:5]
