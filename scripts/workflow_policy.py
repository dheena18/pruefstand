"""Allow-lists of the workflow guard (T0.2 S3, S3d), kept as data and not as scattered conditions.

Every entry carries its reason. Adding an entry is a security decision: it needs a row in
``docs/decisions.md`` and a line in ``docs/engineering/ci-cd.md`` §1.
"""

GATE_ROUTER = "gate-router.yml"
GATE_ROUTER_ENV = "gate-router"
GATE_ROUTER_SECRETS = frozenset({"BOT_APP_ID", "BOT_APP_KEY"})
APP_TOKEN_ACTION = "actions/create-github-app-token@"  # noqa: S105 (an action name, not a secret)

# Files that may grant ``id-token: write`` (ci-cd.md §1; deploy.yml needs no OIDC token, A12-M7).
ID_TOKEN_FILES = frozenset({"build-images.yml", "docs.yml", "release.yml"})

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
        "deploy",
    ): "downloads the dashboard-site artefact of the triggering deploy.yml run",
    ("live-e2e.yml", "live"): "downloads the main baseline artefact by run id",
}

# (file, job) -> reason, for ``contents: write``.
CONTENTS_WRITE: dict[tuple[str, str], str] = {
    ("release.yml", "release-assets"): "attaches image-digests.json to the GitHub release",
    ("cassettes.yml", "record"): "pushes its own cassettes/<date> branch, never opens a PR",
    ("demo-ready.yml", "release-demo-ready"): "uploads the demo-ready.json release asset (D318)",
}

# (file, job) -> reason, for ``statuses: write``.
STATUSES_WRITE: dict[tuple[str, str], str] = {
    ("build-images.yml", "push-sign"): "posts the pruefstand/image commit status",
}

# Jobs of build-images.yml must check out the PR head SHA, never the merge commit (R9 X2.4).
BUILD_IMAGES = "build-images.yml"
BUILD_IMAGES_REF = "${{ github.event.pull_request.head.sha || github.sha }}"
