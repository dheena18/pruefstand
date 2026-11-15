#!/usr/bin/env bash
# Connect a Claude Code cloud session to the VM `pruefstand-exec` over Tailscale.
# Run once at the start of each cloud session:  bash scripts/cloud/connect-vm.sh
# Needs the cloud environment variables TS_AUTHKEY and VM_SSH_KEY (base64, one line) and the
# Tailscale package (installed by the environment's setup script). See docs/ops/setup-log.md §9.
set -euo pipefail

: "${TS_AUTHKEY:?TS_AUTHKEY is not set in the cloud environment}"
: "${VM_SSH_KEY:?VM_SSH_KEY is not set in the cloud environment}"
VM_HOST="${VM_HOST:-pruefstand-exec}"
VM_USER="${VM_USER:?set VM_USER (the owner login on the VM) in the cloud environment}"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo -E"; fi

if ! command -v ssh >/dev/null 2>&1; then
  echo "ssh client not installed; installing openssh-client" >&2
  $SUDO apt-get update -qq && $SUDO apt-get install -y -qq openssh-client
fi

if ! command -v tailscale >/dev/null 2>&1; then
  echo "tailscale not installed; installing" >&2
  # Pinned static tarball (no `curl | sh`): the SHA-256 below is checked before anything is unpacked.
  # To bump: take the new tailscale_<version>_amd64.tgz and its .sha256 from https://pkgs.tailscale.com/stable/.
  TS_VERSION="1.104.7"
  TS_SHA256="e56693ff74a64f2591b7e819c280635a100aae1ddfb0ef058fcd052b7cd8d16c"
  if [ "$(uname -m)" != "x86_64" ]; then
    echo "pinned tailscale tarball is amd64 only; install tailscale manually on $(uname -m)" >&2
    exit 1
  fi
  ts_dir="$(mktemp -d)"
  curl -fsSL --retry 3 --retry-all-errors --retry-delay 5 -o "$ts_dir/ts.tgz" \
    "https://pkgs.tailscale.com/stable/tailscale_${TS_VERSION}_amd64.tgz"
  if ! echo "$TS_SHA256  $ts_dir/ts.tgz" | sha256sum -c - >/dev/null 2>&1; then
    echo "tailscale tarball SHA-256 mismatch; refusing to install" >&2
    rm -rf "$ts_dir"
    exit 1
  fi
  tar -xzf "$ts_dir/ts.tgz" -C "$ts_dir"
  $SUDO install -m 0755 "$ts_dir/tailscale_${TS_VERSION}_amd64/tailscale" /usr/local/bin/tailscale
  $SUDO install -m 0755 "$ts_dir/tailscale_${TS_VERSION}_amd64/tailscaled" /usr/local/bin/tailscaled
  rm -rf "$ts_dir"
fi

# Userspace networking: cloud VMs may not allow a TUN device. The daemon is per session.
if ! $SUDO tailscale status >/dev/null 2>&1; then
  ($SUDO tailscaled --tun=userspace-networking --state=mem: > /tmp/tailscaled.log 2>&1 &)
  sleep 3
fi
$SUDO tailscale up --authkey="$TS_AUTHKEY" --hostname=claude-cloud --accept-dns=false --timeout=60s

# SSH key and host alias (the key arrives base64-encoded on one line)
mkdir -p ~/.ssh && chmod 700 ~/.ssh
printf '%s' "$VM_SSH_KEY" | base64 -d > ~/.ssh/id_vm
chmod 600 ~/.ssh/id_vm
if ! grep -q '^Host vm$' ~/.ssh/config 2>/dev/null; then
  cat >> ~/.ssh/config <<EOF
Host vm
  HostName ${VM_HOST}
  User ${VM_USER}
  IdentityFile ~/.ssh/id_vm
  IdentitiesOnly yes
  ProxyCommand ${SUDO:+sudo }tailscale nc %h %p
  ServerAliveInterval 30
  StrictHostKeyChecking accept-new
EOF
  chmod 600 ~/.ssh/config
fi

ssh vm 'echo "connected to $(hostname)"; curl -s http://127.0.0.1:11434/api/tags | head -c 120; echo'
