#!/usr/bin/env bash
# Connect a Claude Code cloud session to the VM `pruefstand-exec` over Tailscale.
# Run once at the start of each cloud session:  bash scripts/cloud/connect-vm.sh
# Needs the cloud environment variables TS_AUTHKEY and VM_SSH_KEY (base64, one line) and the
# Tailscale package (installed by the environment's setup script). See docs/ops/setup-log.md §9.
set -euo pipefail

: "${TS_AUTHKEY:?TS_AUTHKEY is not set in the cloud environment}"
: "${VM_SSH_KEY:?VM_SSH_KEY is not set in the cloud environment}"
VM_HOST="${VM_HOST:-pruefstand-exec}"
VM_USER="${VM_USER:-dheena}"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo -E"; fi

if ! command -v ssh >/dev/null 2>&1; then
  echo "ssh client not installed; installing openssh-client" >&2
  $SUDO apt-get update -qq && $SUDO apt-get install -y -qq openssh-client
fi

if ! command -v tailscale >/dev/null 2>&1; then
  echo "tailscale not installed; installing" >&2
  curl -fsSL https://tailscale.com/install.sh | $SUDO sh
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
