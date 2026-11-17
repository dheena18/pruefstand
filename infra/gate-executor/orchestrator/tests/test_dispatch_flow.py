"""dispatch (D288, P4.2, D1095): selection to statuses and processed.jsonl, API-shaped inputs."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from gate_orchestrator.dispatch_flow import Deps, load_maintainers, run_dispatch
from gate_orchestrator.jobs import AWAITING_IMAGE, FORK_MOVED, load_gated_paths
from gate_orchestrator.models import Dispatch, Job
from gate_orchestrator.state import load_processed
from orch_testkit import SpyPoster

from pruefstand.core.errors import ConfigError

REPO = "dheena18/pruefstand"
HEAD = "a" * 40
NOW = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)


@dataclass
class Reader:
    """The public API answers of one PR (shapes of GET pulls/{n}, pulls/{n}/files, status)."""

    files_list: list[str]
    head_repo: str = REPO
    statuses_list: list[dict[str, Any]] = field(default_factory=list)
    mirror: str | None = None

    def pull(self, number: int) -> dict[str, Any]:
        return {
            "number": number,
            "head": {"sha": HEAD, "repo": {"full_name": self.head_repo}},
            "base": {"repo": {"full_name": REPO}},
        }

    def files(self, number: int) -> list[str]:
        return self.files_list

    def statuses(self, sha: str) -> list[dict[str, Any]]:
        return self.statuses_list

    def branch_head(self, branch: str) -> str | None:
        assert branch == "gate/pr-7"
        return self.mirror


IMAGE_OK = {"context": "pruefstand/image", "state": "success", "description": "sha256:" + "b" * 64}


def _deps(tmp: Path, reader: Reader, gate_runs: list[Job]) -> tuple[Deps, SpyPoster]:
    poster = SpyPoster()

    def run_gate(job: Job) -> str:
        gate_runs.append(job)
        return "PASS"

    deps = Deps(
        reader=reader,
        poster=poster,
        run_gate=run_gate,
        processed=tmp / "state" / "processed.jsonl",
        gated_paths=load_gated_paths(),
        maintainers=frozenset({"dheena18"}),
        now=lambda: NOW,
    )
    return deps, poster


def _dispatch(actor: str = "dheena18") -> Dispatch:
    return Dispatch(pr=7, actor=actor, dispatch_run_id=99)


def test_the_owner_is_the_only_maintainer() -> None:
    assert load_maintainers() == frozenset({"dheena18"})


def test_an_actor_outside_maintainers_is_refused_without_status(tmp_path: Path) -> None:
    deps, poster = _deps(tmp_path, Reader(["apps/rag-demo/src/rag_demo/api.py"]), [])
    with pytest.raises(ConfigError):
        run_dispatch(_dispatch("someone-else"), deps)
    assert poster.calls == []
    assert load_processed(deps.processed) == []


def test_no_gated_path_posts_and_records_nothing(tmp_path: Path) -> None:
    deps, poster = _deps(tmp_path, Reader(["docs/index.md"]), [])
    assert run_dispatch(_dispatch(), deps) == 0
    assert poster.calls == []
    assert load_processed(deps.processed) == []


def test_without_image_status_it_posts_pending_once(tmp_path: Path) -> None:
    reader = Reader(["apps/rag-demo/src/rag_demo/api.py"])
    deps, poster = _deps(tmp_path, reader, [])
    assert run_dispatch(_dispatch(), deps) == 0
    assert poster.calls == [("post_status", HEAD, "pending", AWAITING_IMAGE, "pruefstand/gate")]
    (entry,) = load_processed(deps.processed)
    assert (entry.result, entry.head_sha, entry.dispatch_run_id) == ("pending", HEAD, 99)
    reader.statuses_list = [
        {"context": "pruefstand/gate", "state": "pending", "description": AWAITING_IMAGE}
    ]
    poster.calls.clear()
    run_dispatch(_dispatch(), deps)
    assert poster.calls == []


def test_a_gated_pr_with_image_runs_the_gate_and_records_its_result(tmp_path: Path) -> None:
    runs: list[Job] = []
    reader = Reader(["apps/rag-demo/src/rag_demo/api.py"], statuses_list=[IMAGE_OK])
    deps, _ = _deps(tmp_path, reader, runs)
    assert run_dispatch(_dispatch(), deps) == 0
    assert [(j.kind, j.sha, j.pr_number) for j in runs] == [("gate", HEAD, 7)]
    assert [e.result for e in load_processed(deps.processed)] == ["PASS"]


def test_a_fork_whose_mirror_moved_gets_pending(tmp_path: Path) -> None:
    reader = Reader(
        ["apps/rag-demo/src/rag_demo/api.py"],
        head_repo="someone/pruefstand",
        statuses_list=[IMAGE_OK],
        mirror="c" * 40,
    )
    runs: list[Job] = []
    deps, poster = _deps(tmp_path, reader, runs)
    run_dispatch(_dispatch(), deps)
    assert runs == []
    assert poster.calls == [("post_status", HEAD, "pending", FORK_MOVED, "pruefstand/gate")]


def test_a_fork_mirrored_at_its_head_is_gated(tmp_path: Path) -> None:
    reader = Reader(
        ["apps/rag-demo/src/rag_demo/api.py"],
        head_repo="someone/pruefstand",
        statuses_list=[IMAGE_OK],
        mirror=HEAD,
    )
    runs: list[Job] = []
    deps, _ = _deps(tmp_path, reader, runs)
    run_dispatch(_dispatch(), deps)
    assert [j.sha for j in runs] == [HEAD]
