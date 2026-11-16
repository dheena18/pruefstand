#!/usr/bin/env bash
# install_runner.sh (T6.2a S9, D1021): first install of the PERSISTENT runner of the private executor repo.
# Run once by the owner on the VM as the service user:  sudo -u pruefstand bash install_runner.sh
# Needs RUNNER_VERSION and RUNNER_SHA256 (the pinned release and its sha256, from the GitHub release page);
# the registration token is typed by the owner when config.sh asks (it expires after 1 h; never stored).
# Not ephemeral (D100) and auto-update stays on (A13-M9; run.sh restarts the listener after an update).
# The user, /var/lib/pruefstand and the tunnel unit come from T0.7; this script never creates them.
# Root steps (system unit, sudoers line) are printed, not run.
# Env: RUNNER_DIR (default /home/pruefstand/pruefstand/runner), RUNNER_REPO_URL (default the private repo),
#      INSTALL_DRY_RUN=1 prints the commands instead of running them.
set -euo pipefail

die() { echo "install_runner: $1" >&2; exit "${2:-1}"; }
run() { if [ "${INSTALL_DRY_RUN:-0}" = 1 ]; then echo "+ $*"; else "$@"; fi; }

[ "$(id -un)" = pruefstand ] || die "run as user pruefstand (sudo -u pruefstand bash install_runner.sh)" 2
: "${RUNNER_VERSION:?set RUNNER_VERSION (pinned actions-runner release, e.g. 2.x.y)}"
: "${RUNNER_SHA256:?set RUNNER_SHA256 (sha256 of the linux-x64 tarball of that release)}"
[[ "$RUNNER_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "RUNNER_VERSION must be x.y.z" 2
[[ "$RUNNER_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "RUNNER_SHA256 must be 64 hex digits" 2

dir="${RUNNER_DIR:-/home/pruefstand/pruefstand/runner}"
url="${RUNNER_REPO_URL:-https://github.com/dheena18/pruefstand-gate}"
here="$(cd "$(dirname "$0")" && pwd)"
tarball="actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"

[ ! -e "$dir/.runner" ] || die "a runner is already configured in $dir (re-registration: runbook section 2)" 2
run mkdir -p "$dir"
run cd "$dir"
run curl -fsSL -o "$tarball" "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${tarball}"
if [ "${INSTALL_DRY_RUN:-0}" = 1 ]; then
  echo "+ sha256sum -c ($RUNNER_SHA256  $tarball)"
else
  echo "$RUNNER_SHA256  $tarball" | sha256sum -c - || die "sha256 mismatch for $tarball"
fi
run tar -xzf "$tarball"
run rm -f "$tarball"
# Interactive: config.sh asks for the registration token (never on a command line, never in a file)
run ./config.sh --url "$url" --name pruefstand-exec --labels a40 --work _work
run cp "$here/runner.env.example" "$dir/.env"

cat <<EOF
Runner installed in $dir. As root (owner), once:
  install -m 0644 $here/pruefstand-runner.service /etc/systemd/system/pruefstand-runner.service
  install -m 0440 $here/sudoers.d/pruefstand-tunnel /etc/sudoers.d/pruefstand-tunnel && visudo -c
  systemctl daemon-reload && systemctl enable --now pruefstand-runner.service
Then, as pruefstand: bash $here/check-host.sh
EOF
