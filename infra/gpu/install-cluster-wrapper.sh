#!/usr/bin/env bash
# install-cluster-wrapper.sh [--print-sudoers]: install pruefstand-cluster and its sudoers line (OWNER step, needs sudo).
#
#   sudo infra/gpu/install-cluster-wrapper.sh
#
# Installs infra/gpu/pruefstand-cluster to /usr/local/bin/pruefstand-cluster (root:root 0755) and ONE sudoers file,
# /etc/sudoers.d/pruefstand-cluster (0440), checked with `visudo -c -f` BEFORE it is moved into place; a file that fails
# the check is never installed. The sudoers file lets group pruefstand run exactly that one wrapper as user
# pruefstand and keeps PRUEFSTAND_LOCK_HELD through sudo (the wrapper's lock proof, A12-M5). --print-sudoers prints the
# file and changes nothing. DESTDIR (a test seam) installs below that directory without needing root.
# Exit: 0 ok, 1 visudo refused the file, 2 not run with sudo.
set -euo pipefail

GPU_DIR="$(cd "$(dirname "$0")" && pwd)"
sudoers() {
  cat <<'FRAGMENT'
# /etc/sudoers.d/pruefstand-cluster (T3.1a, installed by infra/gpu/install-cluster-wrapper.sh)
# Group pruefstand (the owner login user is a member) may run ONE wrapper as user pruefstand, the only holder of
# the cluster key. The wrapper accepts fixed ops only and checks that the GPU lock is held for the mutating ones.
Defaults!/usr/local/bin/pruefstand-cluster env_keep += "PRUEFSTAND_LOCK_HELD"
%pruefstand ALL=(pruefstand) NOPASSWD: /usr/local/bin/pruefstand-cluster
FRAGMENT
}

if [ "${1:-}" = "--print-sudoers" ]; then
  sudoers
  exit 0
fi
[ "$#" -eq 0 ] || {
  echo "usage: install-cluster-wrapper.sh [--print-sudoers]" >&2
  exit 64
}
dest="${DESTDIR:-}"
if [ -z "$dest" ] && [ "$(id -u)" -ne 0 ]; then
  echo "install-cluster-wrapper.sh: run it with sudo (it writes /usr/local/bin and /etc/sudoers.d)" >&2
  exit 2
fi
owner=()
[ -n "$dest" ] || owner=(-o root -g root)

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
sudoers >"$stage/pruefstand-cluster.sudoers"
if ! visudo -c -f "$stage/pruefstand-cluster.sudoers"; then
  echo "install-cluster-wrapper.sh: visudo refused the sudoers file; nothing installed" >&2
  exit 1
fi
mkdir -p "$dest/usr/local/bin" "$dest/etc/sudoers.d"
install -m 0755 "${owner[@]}" "$GPU_DIR/pruefstand-cluster" "$dest/usr/local/bin/pruefstand-cluster"
install -m 0440 "${owner[@]}" "$stage/pruefstand-cluster.sudoers" "$dest/etc/sudoers.d/pruefstand-cluster"
echo "installed $dest/usr/local/bin/pruefstand-cluster and $dest/etc/sudoers.d/pruefstand-cluster"
