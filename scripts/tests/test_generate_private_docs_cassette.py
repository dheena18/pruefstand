"""``generate_private_docs.main`` on the recorded answers of the real local judge model (T2.6a).

Recorded by ``record_cassettes.sh --private-docs``; this test replays them through the script's own
``main``. It checks the plumbing (prompt, request, output check, front matter, resume) on REAL model
text, not what the model writes: a re-recording may change the prose, never these rules.
"""

from pathlib import Path

import pytest
from generate_private_docs import main
from private_doc_plan import check_output, plan_all
from testsupport.private_docs_cassette import ARGS, draft_dir, recorded, route_backend

from pruefstand.attacks.canary import TENANT_PREFIX
from pruefstand.ingest.private_docs import parse_private_doc

pytestmark = pytest.mark.skipif(
    not recorded(), reason="no private-doc cassettes yet (record_cassettes.sh --private-docs)"
)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_LOCK_HELD", "1")
    route_backend(monkeypatch, "replay", None)


def test_every_recorded_answer_becomes_an_accepted_draft(tmp_path: Path) -> None:
    assert main([*ARGS, "--drafts", str(draft_dir(tmp_path))]) == 0
    plans = plan_all(2, 7)
    for tenant in TENANT_PREFIX:
        for plan in plans[tenant]:
            path = draft_dir(tmp_path) / tenant / f"{plan.front.doc_id}.md"
            text = path.read_text(encoding="utf-8")
            front, body = parse_private_doc(text, path.name)
            assert front.tenant == tenant
            assert front.semantic_fact == plan.front.semantic_fact
            assert body.count(front.semantic_fact) == 1
            assert "CANARY" not in text
            assert check_output(body + "\n[ENDE]", plan) == body


def test_a_second_run_over_the_drafts_makes_no_call(tmp_path: Path) -> None:
    drafts = str(draft_dir(tmp_path))
    assert main([*ARGS, "--drafts", drafts]) == 0
    before = sorted(p.read_bytes() for p in draft_dir(tmp_path).rglob("*.md"))
    assert main([*ARGS, "--drafts", drafts]) == 0  # all skipped: a cassette miss would raise
    assert before == sorted(p.read_bytes() for p in draft_dir(tmp_path).rglob("*.md"))
