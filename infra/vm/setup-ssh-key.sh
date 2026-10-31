#!/usr/bin/env bash
# setup-ssh-key.sh: the VM -> cluster SSH identity of user `pruefstand` (Y1, setup log section 2).
#
# Run as the service user:  sudo -u pruefstand infra/vm/setup-ssh-key.sh [--host H --port P --user U]
# On the real VM this was done by hand on 2026-10-31, so the script only VERIFIES: an existing key and
# an existing `Host cairo-s101lp` block are kept byte for byte (missing options are only reported).
#   * creates ~/.ssh/id_ed25519_cluster (ed25519, no passphrase) if missing; the key never leaves this home
#   * appends the `Host cairo-s101lp` block only if absent (needs --host/--port/--user; values live only here)
#   * verifies `ssh -o BatchMode=yes cairo-s101lp true`; if it fails, prints the one-time ssh-copy-id line
# Options: --home DIR (tests only; otherwise the script refuses to run as any user but pruefstand)
#          --no-verify (skip the ssh login test)
# Exit: 0 ok, 1 login test failed, 2 usage / wrong user.
set -euo pipefail

SVC_HOME=/home/pruefstand
HOME_DIR=""
HOST=""
PORT=""
CUSER=""
VERIFY=1
ALIAS=cairo-s101lp
KEY_NAME=id_ed25519_cluster
WANTED=(HostName Port User IdentityFile IdentitiesOnly ServerAliveInterval ServerAliveCountMax ExitOnForwardFailure)

while [ "$#" -gt 0 ]; do
  case "$1" in
    --home) HOME_DIR="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --user) CUSER="$2"; shift 2 ;;
    --no-verify) VERIFY=0; shift ;;
    -h | --help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$HOME_DIR" ]; then
  if [ "$(id -un)" != pruefstand ]; then
    echo "setup-ssh-key: run as the service user: sudo -u pruefstand $0 ... (the key must not live in another home)" >&2
    exit 2
  fi
  HOME_DIR="$SVC_HOME"
fi
SSH_DIR="$HOME_DIR/.ssh"
KEY="$SSH_DIR/$KEY_NAME"
CONFIG="$SSH_DIR/config"

mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"

if [ -f "$KEY" ]; then
  echo "OK   key $KEY exists (kept)"
else
  ssh-keygen -q -t ed25519 -N '' -C "pruefstand-exec to cluster" -f "$KEY"
  echo "DO   created $KEY"
fi
[ -f "$KEY.pub" ] || ssh-keygen -y -f "$KEY" >"$KEY.pub"
chmod 600 "$KEY"
chmod 644 "$KEY.pub"

block_exists() { [ -f "$CONFIG" ] && grep -qE "^Host[[:space:]]+${ALIAS}[[:space:]]*$" "$CONFIG"; }

block_text() {
  awk -v alias="$ALIAS" '
    $1 == "Host" { inblock = ($2 == alias); next }
    inblock { print }
  ' "$CONFIG"
}

write_block() {
  if [ -z "$HOST" ] || [ -z "$PORT" ] || [ -z "$CUSER" ]; then
    echo "setup-ssh-key: no 'Host $ALIAS' block yet; pass --host, --port and --user (stored only in $CONFIG)" >&2
    exit 2
  fi
  local gap=""
  if [ -s "$CONFIG" ]; then gap=$'\n'; fi
  {
    printf '%s' "$gap"
    cat <<BLOCK
Host $ALIAS
    HostName $HOST
    Port $PORT
    User $CUSER
    IdentityFile ~/.ssh/$KEY_NAME
    IdentitiesOnly yes
    ServerAliveInterval 30
    ServerAliveCountMax 3
    ExitOnForwardFailure yes
BLOCK
  } >>"$CONFIG"
  echo "DO   wrote Host $ALIAS block to $CONFIG"
}

report_block() {
  local text opt
  text="$(block_text)"
  for opt in "${WANTED[@]}"; do
    if ! grep -qiE "^[[:space:]]*${opt}[[:space:]]" <<<"$text"; then
      echo "WARN existing Host $ALIAS block has no $opt (kept as is; add it by hand)"
    fi
  done
  echo "OK   Host $ALIAS block exists (kept)"
}

if block_exists; then report_block; else write_block; fi
chmod 600 "$CONFIG"

copy_id_hint() {
  echo "Install the public key once (the cluster password is typed once and never stored):"
  echo "  sudo -u pruefstand ssh-copy-id -i $SVC_HOME/.ssh/$KEY_NAME.pub -p ${PORT:-<port>} ${CUSER:-<user>}@${HOST:-<host>}"
  echo "If the key is offered but a password is still asked, run on the cluster: chmod g-w ~"
}

if [ "$VERIFY" -eq 0 ]; then
  copy_id_hint
  exit 0
fi
if ssh -F "$CONFIG" -o BatchMode=yes -o PreferredAuthentications=publickey -o ConnectTimeout=15 "$ALIAS" true; then
  echo "OK   BatchMode login to $ALIAS works"
else
  echo "FAIL BatchMode login to $ALIAS failed"
  copy_id_hint
  exit 1
fi
