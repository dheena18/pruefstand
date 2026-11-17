"""verify_image: exact cosign identity, revision label == PR head SHA (ci-cd.md §7, X2.4)."""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from gate_orchestrator.image import ImageVerificationError, cosign_argv, verify_image

ROOT = Path(__file__).resolve().parents[4]
DIGEST = "sha256:" + "b" * 64
HEAD, MERGE = "1" * 40, "2" * 40


class Docker:
    def __init__(self, *, cosign: int = 0, revision: str | None = HEAD) -> None:
        self.cosign, self.revision = cosign, revision
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> tuple[int, str]:
        self.calls.append(list(argv))
        if argv[0] == "cosign":
            return self.cosign, ""
        labels = (
            {} if self.revision is None else {"org.opencontainers.image.revision": self.revision}
        )
        return 0, json.dumps(labels)


def test_cosign_argv_has_the_ci_cd_identity_and_issuer() -> None:
    argv = cosign_argv("ref")
    regexp = argv[argv.index("--certificate-identity-regexp") + 1]
    assert (
        argv[argv.index("--certificate-oidc-issuer") + 1]
        == "https://token.actions.githubusercontent.com"
    )
    ci_cd = (ROOT / "docs/engineering/ci-cd.md").read_text(encoding="utf-8")
    assert f"--certificate-identity-regexp '{regexp.replace('|', chr(92) + '|')}'" in ci_cd


def test_matching_head_revision_passes() -> None:
    docker = Docker()
    assert verify_image(DIGEST, HEAD, docker) == f"ghcr.io/dheena18/rag-demo@{DIGEST}"
    assert docker.calls[0][:2] == ["cosign", "verify"]


@pytest.mark.parametrize("revision", [MERGE, None, ""])
def test_revision_other_than_the_head_fails(revision: str | None) -> None:
    with pytest.raises(ImageVerificationError, match="image verification failed: revision"):
        verify_image(DIGEST, HEAD, Docker(revision=revision))


def test_cosign_failure_fails_before_inspect() -> None:
    docker = Docker(cosign=1)
    with pytest.raises(ImageVerificationError, match="cosign exit 1"):
        verify_image(DIGEST, HEAD, docker)
    assert len(docker.calls) == 1


@pytest.mark.parametrize(
    ("digest", "sha"), [("sha256:abc", HEAD), ("latest", HEAD), (DIGEST, "main")]
)
def test_malformed_inputs_fail(digest: str, sha: str) -> None:
    with pytest.raises(ImageVerificationError, match="image verification failed"):
        verify_image(digest, sha, Docker())
