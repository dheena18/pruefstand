"""Allow-lists of the workflow guard (T0.2 S3, S3d), kept as data and not as scattered conditions.

Every entry carries its reason. Adding an entry is a security decision: it needs a row in
``docs/decisions.md`` and a line in ``docs/engineering/ci-cd.md`` §1.
"""

import re

GATE_ROUTER = "gate-router.yml"
GATE_ROUTER_ENV = "gate-router"
GATE_ROUTER_SECRETS = frozenset({"BOT_APP_ID", "BOT_APP_KEY"})
APP_TOKEN_ACTION = "actions/create-github-app-token@"  # noqa: S105 (an action name, not a secret)

# (file, job) -> reason, for ``id-token: write`` (ci-cd.md §1; never at workflow level;
# deploy.yml needs no OIDC token, A12-M7).
ID_TOKEN_WRITE: dict[tuple[str, str], str] = {
    ("build-images.yml", "push-sign"): "keyless cosign signing of the pushed image",
    ("docs.yml", "deploy"): "actions/deploy-pages (OIDC), the only Pages writer",
    ("release.yml", "publish-pypi"): "PyPI trusted publishing",
    ("release.yml", "publish-testpypi"): "TestPyPI trusted publishing",
    ("release.yml", "sign"): "keyless cosign signing of the release images",
    ("release.yml", "attest"): "build provenance attestation",
}

# (file, job) -> reason, for ``pages: write``.
PAGES_WRITE: dict[tuple[str, str], str] = {
    ("docs.yml", "deploy"): "publishes the one GitHub Pages artefact (D243)",
}

# Files that may grant ``models: read`` (security.md X2); ``models: write`` is never allowed.
MODELS_READ_FILES = frozenset({"live-e2e.yml", "cassettes.yml"})

# (file, job) -> reason, for ``actions: read`` (R13 P5.2).
ACTIONS_READ: dict[tuple[str, str], str] = {
    (
        "demo-ready.yml",
        "fetch-artefacts",
    ): "downloads the triggering release.yml run's artefact (D301)",
    (
        "docs.yml",
        "site",
    ): "downloads the dashboard-site artefact of the triggering deploy.yml run",
    ("live-e2e.yml", "live"): "downloads the main baseline artefact by run id",
}

# (file, job) -> reason, for ``contents: write``.
CONTENTS_WRITE: dict[tuple[str, str], str] = {
    ("release.yml", "release-assets"): "attaches image-digests.json to the GitHub release",
    (
        "cassettes.yml",
        "push",
    ): "pushes its own cassettes/<date>-<run> branch, runs no repo code, never opens a PR",
    ("demo-ready.yml", "release-demo-ready"): "uploads the demo-ready.json release asset (D318)",
}

# (file, job) -> reason, for ``statuses: write``.
STATUSES_WRITE: dict[tuple[str, str], str] = {
    ("build-images.yml", "push-sign"): "posts the pruefstand/image commit status",
}

# Jobs of build-images.yml must check out the PR head SHA, never the merge commit (R9 X2.4).
BUILD_IMAGES = "build-images.yml"
BUILD_IMAGES_REF = "${{ github.event.pull_request.head.sha || github.sha }}"

# Expression-injection rule: `${{ }}` expressions are normalised (brackets to dots, lower case).
EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
BRACKET_NAME = re.compile(r"\[\s*['\"]([^'\"]+)['\"]\s*\]")
# Attacker-controlled context values (GitHub security hardening guide), matched on the normalised
# (lower-case, dotted) expression.
UNTRUSTED = re.compile(
    r"github\.(head_ref|base_ref)\b"
    r"|github\.event\.(pull_request|issue|discussion)\.(title|body)\b"
    r"|github\.event\.pull_request\.head\.(ref|label|repo\.default_branch)\b"
    r"|github\.event\.(comment|review|review_comment)\.body\b"
    r"|github\.event\.head_commit\.(message|author\.(email|name))\b"
    r"|github\.event\.commits[\w.\[\]*]*\.(message|author\.(email|name))\b"
    r"|github\.event\.pages[\w.\[\]*]*\.page_name\b"
    r"|github\.event\.workflow_run\.(head_branch|display_title|head_commit\.message)\b"
)
FETCH_PR_CODE = re.compile(
    r"git\s+(fetch|clone)\b|gh\s+pr\s+checkout\b|gh\s+pr\s+diff\b[^\n]*--patch[^\n]*\|\s*(ba|z)?sh\b"
)


# (file, job) -> reason: jobs that hold a write token and therefore must run NO repository code
# (no uv/make/python/scripts steps, only these actions, exactly the listed permissions).
NO_REPO_CODE_JOBS: dict[tuple[str, str], dict[str, str]] = {
    ("cassettes.yml", "push"): {"contents": "write"},
}
NO_REPO_CODE_ACTIONS = ("actions/checkout@", "actions/download-artifact@")
REPO_CODE_RUN = re.compile(
    r"(?:^|[\s;&|(])(?:(?:uv|make|python3?|pytest|pip|npm|pnpm|node)(?=$|[\s;&|)])"
    r"|(?:bash|sh)\s+\S*scripts/|\./\S+)",
    re.MULTILINE,
)
