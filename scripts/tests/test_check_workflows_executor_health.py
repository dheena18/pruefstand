"""Guard rule for executor-health.yml (T6.2b S8, D1092): exact job rights, no secrets."""

from pathlib import Path

from check_workflows import check_text

REPO = Path(__file__).resolve().parents[2]
NAME = "executor-health.yml"
TEXT = (REPO / ".github" / "workflows" / NAME).read_text(encoding="utf-8")


def test_committed_executor_health_passes() -> None:
    assert check_text(NAME, TEXT) == []


def test_committed_executor_health_shape() -> None:
    assert "43 * * * *" in TEXT
    assert "workflow_dispatch" in TEXT
    assert "/heartbeat/heartbeat.json" in TEXT
    assert "self-hosted" not in TEXT


def test_extra_permission_fails() -> None:
    text = TEXT.replace(
        "      issues: write\n", "      issues: write\n      pull-requests: write\n"
    )
    assert any("exactly {contents: read, issues: write}" in f for f in check_text(NAME, text))


def test_missing_issues_write_fails() -> None:
    text = TEXT.replace("      issues: write\n", "")
    assert any("exactly {contents: read, issues: write}" in f for f in check_text(NAME, text))


def test_secret_reference_fails() -> None:
    text = TEXT.replace("${{ github.token }}", "${{ secrets.HEALTH_TOKEN }}")
    assert any("no secrets.*" in f for f in check_text(NAME, text))


def test_issues_write_elsewhere_is_not_allowed() -> None:
    assert any("issues: write" in f for f in check_text("ci.yml", TEXT))
