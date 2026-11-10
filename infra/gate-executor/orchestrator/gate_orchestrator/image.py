"""``verify_image``: origin check of the candidate image (S3; ci-cd.md §7, X2.4, D107).

``cosign verify`` with the build-images identity and the GitHub OIDC issuer proves only the image's
**origin** (built by this repo's Actions), never that its content is safe: the candidate stays
untrusted and is contained by the sandbox. The image label ``org.opencontainers.image.revision``
must equal the PR **head** SHA being gated (``pull/N/merge`` in the identity is the workflow ref,
not the content). Commands go through an injected runner; the image is pulled anonymously by digest.
"""

import json
import re
from collections.abc import Callable, Sequence

from pruefstand.core.errors import PruefstandError

IDENTITY_REGEXP = (
    r"^https://github.com/dheena18/pruefstand/\.github/workflows/build-images\.yml"
    r"@refs/(heads/.+|pull/[0-9]+/merge)$"
)
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
IMAGE = "ghcr.io/dheena18/rag-demo"
REVISION_LABEL = "org.opencontainers.image.revision"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
Runner = Callable[[Sequence[str]], tuple[int, str]]


class ImageVerificationError(PruefstandError):
    """``image verification failed: <reason>`` (the orchestrator exits 3)."""


def image_ref(digest: str) -> str:
    """``ghcr.io/dheena18/rag-demo@sha256:<d>``; refuses anything but a sha256 digest."""
    if not DIGEST.fullmatch(digest):
        msg = "image verification failed: digest is not sha256:<64 hex>"
        raise ImageVerificationError(msg)
    return f"{IMAGE}@{digest}"


def cosign_argv(ref: str) -> list[str]:
    """The exact ``cosign verify`` argv (identity regexp identical to ci-cd.md §7)."""
    return [
        "cosign", "verify",
        "--certificate-identity-regexp", IDENTITY_REGEXP,
        "--certificate-oidc-issuer", OIDC_ISSUER,
        ref,
    ]  # fmt: skip


def verify_image(digest: str, sha: str, run: Runner) -> str:
    """Verify signature origin and revision label; return the image ref to run.

    Args:
        digest: ``sha256:<64 hex>`` from the ``pruefstand/image`` status.
        sha: the PR head SHA being gated (never the merge commit).
        run: ``argv -> (exit code, stdout)``.

    Returns:
        The digest-pinned image ref.

    Raises:
        ImageVerificationError: bad digest/SHA, cosign failed, or the revision label differs.
    """
    if not SHA.fullmatch(sha):
        msg = "image verification failed: gated SHA is not 40 hex"
        raise ImageVerificationError(msg)
    ref = image_ref(digest)
    code, _ = run(cosign_argv(ref))
    if code != 0:
        msg = f"image verification failed: cosign exit {code}"
        raise ImageVerificationError(msg)
    code, out = run(["docker", "image", "inspect", "--format", "{{json .Config.Labels}}", ref])
    labels = json.loads(out) if code == 0 and out.strip() else {}
    revision = labels.get(REVISION_LABEL) if isinstance(labels, dict) else None
    if revision != sha:
        msg = "image verification failed: revision label is not the gated head SHA"
        raise ImageVerificationError(msg)
    return ref
