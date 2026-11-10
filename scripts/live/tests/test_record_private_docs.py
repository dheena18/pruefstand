"""Records the real answers of the local judge model for the private-doc generator (T2.6a).

Run by ``record_cassettes.sh --private-docs`` on the VM under the GPU lock with the day set loaded.
Without ``PRUEFSTAND_RECORD_PRIVATE_DOCS=1`` it is skipped. It runs the script's own ``main`` with a
recording backend (6 documents, 3 tenants x 2); nothing is ever written by hand.
"""

import os
from pathlib import Path

import pytest
from generate_private_docs import main
from testsupport.private_docs_cassette import ARGS, CASSETTES, draft_dir, route_backend

from pruefstand.llm.factory import build_backend

pytestmark = [
    pytest.mark.live,
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.environ.get("PRUEFSTAND_RECORD_PRIVATE_DOCS") != "1",
        reason="set PRUEFSTAND_RECORD_PRIVATE_DOCS=1 (record_cassettes.sh --private-docs)",
    ),
]


def test_the_real_judge_model_writes_six_accepted_drafts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRUEFSTAND_LOCK_HELD", "1")  # set by pruefstand-lock; the script re-checks
    route_backend(monkeypatch, "record", build_backend)
    assert main([*ARGS, "--drafts", str(draft_dir(tmp_path))]) == 0
    drafts = sorted(draft_dir(tmp_path).rglob("*.md"))
    assert len(drafts) == 6
    assert len(list(CASSETTES.glob("*.json"))) >= 6  # one per accepted draft, more after rejections
