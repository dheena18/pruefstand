"""``scripts/slice/restore_snapshot.py``: the HTTP plumbing of the snapshot upload (T1.12)."""

from pathlib import Path

import httpx
import pytest
import respx
from slice.restore_snapshot import main, upload_snapshot

QDRANT = "http://qdrant.test:6333"


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    path = tmp_path / "slice_v2.snapshot"
    path.write_bytes(b"snapshot-bytes")
    return path


def test_upload_posts_the_file_with_snapshot_priority(snapshot: Path) -> None:
    with respx.mock(base_url=QDRANT) as router:
        route = router.post("/collections/slice_v2/snapshots/upload").respond(200, json={})
        upload_snapshot(QDRANT + "/", "slice_v2", snapshot)
    request = route.calls.last.request
    assert request.url.params["priority"] == "snapshot"
    assert request.url.params["wait"] == "true"
    assert b"snapshot-bytes" in request.content


def test_a_rejected_upload_raises(snapshot: Path) -> None:
    with respx.mock(base_url=QDRANT) as router:
        router.post("/collections/slice_v2/snapshots/upload").respond(400)
        with pytest.raises(httpx.HTTPStatusError):
            upload_snapshot(QDRANT, "slice_v2", snapshot)


def test_main_reports_a_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--snapshot", str(tmp_path / "none")]) == 2
    assert "not found" in capsys.readouterr().err


def test_main_uploads_to_the_configured_qdrant(
    snapshot: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("QDRANT_URL", QDRANT)
    monkeypatch.setenv("RAG_COLLECTION", "slice_v2")
    with respx.mock(base_url=QDRANT) as router:
        router.post("/collections/slice_v2/snapshots/upload").respond(200, json={})
        assert main(["--snapshot", str(snapshot)]) == 0
        router.post("/collections/slice_v2/snapshots/upload").respond(500)
        assert main(["--snapshot", str(snapshot)]) == 1
    assert "restored" in capsys.readouterr().out
