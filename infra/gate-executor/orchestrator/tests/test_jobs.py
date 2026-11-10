"""select_jobs for one owner dispatch (round 13 P1.2, D288, X2.2, X2.3, P4.2)."""

import re
from pathlib import Path
from typing import Any

import pytest
from gate_orchestrator.jobs import AWAITING_IMAGE, FORK_MOVED, load_gated_paths, select_jobs
from gate_orchestrator.models import Dispatch, Job

from pruefstand.core.errors import ConfigError

ROOT = Path(__file__).resolve().parents[4]
PKG = Path(__file__).resolve().parents[1] / "gate_orchestrator"
REPO = "dheena18/pruefstand"
HEAD, OTHER = "a" * 40, "b" * 40
MAINTAINERS = frozenset({"owner-login"})
DISPATCH = Dispatch(pr=7, actor="owner-login", dispatch_run_id=99)
IMAGE_OK: dict[str, object] = {"context": "pruefstand/image", "state": "success"}
GATED = load_gated_paths()


def _pr(head_repo: str | None = REPO, number: int = 7) -> dict[str, Any]:
    head: dict[str, Any] = {
        "sha": HEAD,
        "repo": None if head_repo is None else {"full_name": head_repo},
    }
    return {"number": number, "head": head, "base": {"repo": {"full_name": REPO}}}


def _select(
    files: list[str],
    *,
    pr: dict[str, Any] | None = None,
    image: dict[str, object] | None = IMAGE_OK,
    mirror: str | None = None,
    dispatch: Dispatch = DISPATCH,
) -> list[Job]:
    return select_jobs(
        dispatch, pr or _pr(), files, image, GATED, maintainers=MAINTAINERS, mirror_head=mirror
    )


def test_same_repo_gated_pr_with_image_is_one_gate_job_on_the_head() -> None:
    assert _select(["apps/rag-demo/src/rag_demo/x.py"]) == [
        Job(kind="gate", sha=HEAD, pr_number=7, tier="pr")
    ]


def test_actor_not_in_maintainers_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="maintainers"):
        _select(["uv.lock"], dispatch=Dispatch(pr=7, actor="someone-else", dispatch_run_id=1))


def test_pr_data_of_another_pr_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="dispatched PR 7"):
        _select(["uv.lock"], pr=_pr(number=8))


@pytest.mark.parametrize(
    "files",
    [
        ["docs/x.md"],
        ["README.md", "tools/a.py"],
        ["packages/pruefstand/src/pruefstand/cli/x.py"],
        [],
    ],
)
def test_no_gated_path_is_no_job_and_no_status(files: list[str]) -> None:
    assert _select(files) == []


@pytest.mark.parametrize(
    "path",
    [
        "uv.lock",
        "pyproject.toml",
        "infra/docker/x",
        "infra/gpu/y",
        "datasets/core/a.jsonl",
        "packages/pruefstand/src/pruefstand/gate/stats.py",
        "apps/rag-demo/configs/rag.gpu.yaml",
    ],
)
def test_each_gated_path_gives_a_gate_job(path: str) -> None:
    assert [j.kind for j in _select([path])] == ["gate"]


@pytest.mark.parametrize(
    "path", ["apps/rag-demo-old/x", "packages/pruefstand/pyproject.toml", "infra/gpux/y"]
)
def test_lookalike_paths_are_not_gated(path: str) -> None:
    assert _select([path]) == []


@pytest.mark.parametrize("image", [None, {"context": "pruefstand/image", "state": "pending"}])
def test_head_without_image_is_pending_not_gate(image: dict[str, object] | None) -> None:
    assert _select(["uv.lock"], image=image) == [
        Job(kind="pending", sha=HEAD, pr_number=7, tier="pr", reason=AWAITING_IMAGE)
    ]
    assert AWAITING_IMAGE == "awaiting signed image; dispatch again after build-images"


def test_release_please_pr_is_gated_like_any_other() -> None:
    assert [j.kind for j in _select(["uv.lock", "pyproject.toml", "CHANGELOG.md"])] == ["gate"]


def test_a_processed_pr_and_sha_still_runs() -> None:
    assert [j.kind for j in _select(["uv.lock"])] == ["gate"]
    assert [
        j.kind
        for j in _select(
            ["uv.lock"], dispatch=Dispatch(pr=7, actor="owner-login", dispatch_run_id=100)
        )
    ] == ["gate"]


def test_fork_mirrored_at_the_same_head_is_gated_on_that_sha() -> None:
    assert _select(["uv.lock"], pr=_pr("someone/fork"), mirror=HEAD) == [
        Job(kind="gate", sha=HEAD, pr_number=7, tier="pr")
    ]


@pytest.mark.parametrize("mirror", [OTHER, None])
def test_fork_moved_or_unmirrored_is_pending_on_the_fork_head(mirror: str | None) -> None:
    assert _select(["uv.lock"], pr=_pr("someone/fork"), mirror=mirror) == [
        Job(kind="pending", sha=HEAD, pr_number=7, tier="pr", reason=FORK_MOVED)
    ]
    assert FORK_MOVED == "fork head moved since mirroring; re-run mirror_fork_pr.sh"


def test_deleted_fork_repo_counts_as_fork() -> None:
    assert _select(["uv.lock"], pr=_pr(None))[0].reason == FORK_MOVED


def _ci_cd_gated_paths() -> list[str]:
    text = (ROOT / "docs/engineering/ci-cd.md").read_text(encoding="utf-8")
    bullet = text.split("- **Gated paths**", 1)[1].split("For gated PRs", 1)[0]
    bullet = re.sub(r"\([^()]*\)", "", bullet.replace("(root)", ""))
    out: list[str] = []
    for token in re.findall(r"`([^`]+)`", bullet):
        brace = re.fullmatch(r"(.*)\{([^}]*)\}(.*)", token)
        out += [f"{brace[1]}{part}{brace[3]}" for part in brace[2].split(",")] if brace else [token]
    return out


def test_gated_paths_txt_equals_ci_cd_section_5() -> None:
    assert _ci_cd_gated_paths() == GATED
    assert all(p.endswith("/**") or "*" not in p for p in GATED)


def test_no_run_gate_label_and_no_not_gated_status_in_the_package() -> None:
    source = "\n".join(p.read_text(encoding="utf-8") for p in PKG.rglob("*.py"))
    assert "run-gate" not in source
    assert "/labels" not in source
    assert "not gated" not in source
    assert "not_gated" not in source
