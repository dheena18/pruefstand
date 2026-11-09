"""Guard rule D926: every curl in a workflow run step carries the retry flags."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from check_workflows import check_dir, check_text

FLAGS = "--retry 3 --retry-all-errors --retry-delay 5"
WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _check(run: str) -> list[str]:
    job: dict[str, Any] = {"runs-on": "ubuntu-24.04", "steps": [{"run": run}]}
    doc = {"name": "x", "on": "pull_request", "permissions": {}, "jobs": {"j": job}}
    return [f for f in check_text("ci.yml", yaml.safe_dump(doc)) if "curl" in f]


def test_curl_with_all_retry_flags_passes() -> None:
    assert _check(f"curl -fsSL {FLAGS} -o t.tgz https://example.org/t.tgz") == []


def test_multiline_curl_with_flags_passes() -> None:
    run = f"curl -fsSL {FLAGS} -o t.tgz \\\n  https://example.org/t.tgz\necho x | sha256sum -c -"
    assert _check(run) == []


@pytest.mark.parametrize(
    "run",
    [
        "curl -fsSL -o t.tgz https://example.org/t.tgz",
        "curl -fsSL --retry 3 --retry-delay 5 -o t https://example.org/t",
        "curl -fsSL --retry 3 --retry-all-errors -o t https://example.org/t",
        "curl -fsSL --retry 5 --retry-all-errors --retry-delay 5 -o t https://example.org/t",
        "cd /tmp && curl -fsSL -o t https://example.org/t",
        "sudo curl -fsSL -o t https://example.org/t",
        "curl -fsSL -o t \\\n  https://example.org/t",
        "if true; then\n  curl -fsSL -o t https://example.org/t\nfi",
        "if curl -fsSL -o t https://example.org/t; then echo ok; fi",
        "if true; then curl -fsSL -o t https://example.org/t; fi",
        "x=`curl -fsSL https://example.org/t`",
        "FOO=1 curl -fsSL -o t https://example.org/t",
        "time curl -fsSL -o t https://example.org/t",
        "echo u | xargs curl -fsSL -o t",
        "for i in 1 2; do curl -fsSL -o t https://example.org/t; done",
    ],
)
def test_curl_without_full_retry_flags_fails(run: str) -> None:
    assert len(_check(run)) == 1


@pytest.mark.parametrize(
    "run",
    [
        f"if true; then\n  curl -fsSL {FLAGS} -o t https://example.org/t\nfi",
        f"if curl -fsSL {FLAGS} -o t https://example.org/t; then echo ok; fi",
        f"x=`curl -fsSL {FLAGS} https://example.org/t`",
        f"FOO=1 curl -fsSL {FLAGS} -o t https://example.org/t",
        f"time curl -fsSL {FLAGS} -o t https://example.org/t",
        f"echo u | xargs curl -fsSL {FLAGS} -o t",
    ],
)
def test_curl_forms_with_flags_pass(run: str) -> None:
    assert _check(run) == []


@pytest.mark.parametrize(
    "run",
    ["echo curl is used", "python -m curlish", "# curl -fsSL x", "curl-config --version"],
)
def test_non_curl_mentions_are_ignored(run: str) -> None:
    assert _check(run) == []


def test_non_command_mentions_of_curl_are_ignored() -> None:
    assert _check("echo curl is used\nuv run python -m curlish") == []


def test_every_committed_workflow_curl_retries() -> None:
    _count, findings = check_dir(WORKFLOWS)
    assert [f for f in findings if "curl" in f] == []
