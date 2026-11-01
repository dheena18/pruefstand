#!/usr/bin/env bash
# vm_check.sh: health check of the VM `pruefstand-exec` (T0.7 S6; rows V1-V7 of gpu-cluster.md section 0.2).
#
# Prints one line per check:  CHECK <id> <PASS|FAIL|WARN> <detail>   (same format as T0.6); exit 1 on any FAIL.
# Run as the OWNER user (not root, not pruefstand); run `sudo -v` first so the sudo-needing checks work
# (iptables, and ssh / write probes as user pruefstand). It never restarts Docker: that is --restart-drill.
#   vm_check.sh [--owner USER] [ID...]     run all checks, or only the named ids
#   vm_check.sh --confirm ID               record an owner-confirmed check: tunnel-reboot | host-reboot | vscode
#   vm_check.sh --restart-drill [--yes]    refuses (exit 75) while gpu.lock is held and (exit 2) while containers run unless
#                                          --yes; restarts Docker ONCE, checks that pruefstand-firewall was restarted too
#                                          and re-runs the firewall check (R12 N4.2). Use it only when no gate or nightly runs.
#   vm_check.sh --strict ...               WARN counts as failure (exit 1): use it for the S7 evidence run.
# Never run it as root (exit 2; PRUEFSTAND_ALLOW_ROOT=1 exists for the tests only).
# Test/ops overrides (env): PRUEFSTAND_LOCK_DIR PRUEFSTAND_DATA_ROOT PRUEFSTAND_ENV_FILE OS_RELEASE_FILE MEMINFO_FILE FSTAB_FILE
#   TRUENAS_HOST_IP (for the demo probes) PROBE_IMAGE (pin by digest: curlimages/curl@sha256:...) DRILL_WAIT_S
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OWNER="${SUDO_USER:-$(id -un)}"
LOCK_DIR="${PRUEFSTAND_LOCK_DIR:-/var/lib/pruefstand}"
DATA_ROOT="${PRUEFSTAND_DATA_ROOT:-/mnt/pruefstand}"
ENV_FILE="${PRUEFSTAND_ENV_FILE:-$HERE/../../.env}"
OS_RELEASE_FILE="${OS_RELEASE_FILE:-/etc/os-release}"
MEMINFO_FILE="${MEMINFO_FILE:-/proc/meminfo}"
FSTAB_FILE="${FSTAB_FILE:-/etc/fstab}"
CONFIRM_FILE="${PRUEFSTAND_CONFIRM_FILE:-${XDG_STATE_HOME:-$HOME/.local/state}/pruefstand/vm-confirmations}"
PROBE_IMAGE="${PROBE_IMAGE:-curlimages/curl:8.11.1}"
PUBLIC_REPO="${PRUEFSTAND_PUBLIC_REPO:-dheena18/pruefstand}"
GATE_REPO="${PRUEFSTAND_GATE_REPO:-dheena18/pruefstand-gate}"
GW=172.17.0.1
ALL_IDS=(os ram cpu disk docker docker-group docker-gw proxy-net firewall gh-scope users lock-dir data-root
  data-root-rw ssh-key tunnel tunnel-reboot host-reboot vscode)
GIB_KB=$((1024 * 1024))

# ---- result bookkeeping ---------------------------------------------------------------------------
FAILS=0 STRICT=0 CUR="" STATUS=PASS OKS=() NOTES=() EXTRA_FW_NOTE="" CLUSTER_ENDPOINT=""
PROBE_CONTAINERS=() PROBE_NETS=()
begin() { CUR="$1"; STATUS=PASS; OKS=(); NOTES=(); }
ok() { OKS+=("$*"); }
note() {
  local level="$1"
  shift
  NOTES+=("$level: $*")
  if [ "$level" = FAIL ]; then STATUS=FAIL; elif [ "$STATUS" = PASS ]; then STATUS=WARN; fi
}
finish() {
  local detail
  if [ "${#NOTES[@]}" -gt 0 ]; then detail="${NOTES[*]}"; else detail="${OKS[*]:-ok}"; fi
  if [ "$STATUS" = FAIL ] || { [ "$STRICT" -eq 1 ] && [ "$STATUS" = WARN ]; }; then FAILS=$((FAILS + 1)); fi
  echo "CHECK $CUR $STATUS $detail"
}

# shellcheck disable=SC2329,SC2317  # called by the trap below (older ShellCheck reports SC2317)
cleanup() {
  local c n
  for c in ${PROBE_CONTAINERS[@]+"${PROBE_CONTAINERS[@]}"}; do docker rm -f "$c" >/dev/null 2>&1 || true; done
  for n in ${PROBE_NETS[@]+"${PROBE_NETS[@]}"}; do docker network rm "$n" >/dev/null 2>&1 || true; done
}
trap cleanup EXIT INT TERM
redact() { sed -E 's#(://)[^/@[:space:]]*@#\1***@#g'; }

as_root() { if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo -n "$@"; fi; }
as_pf() { sudo -n -u pruefstand "$@"; }
have_sudo() { sudo -n true 2>/dev/null; }
envval() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true; }
members_of() { getent group "$1" 2>/dev/null | cut -d: -f4 | tr ',' '\n' | sed '/^$/d' | sort | tr '\n' ' ' || true; }
avail_kb() { df -Pk "$1" 2>/dev/null | awk 'NR==2 {print $4}' || true; }

# ---- host facts (V1) ------------------------------------------------------------------------------
check_os() {
  begin os
  local id ver
  id="$(grep -E '^ID=' "$OS_RELEASE_FILE" | cut -d= -f2 | tr -d '"' || true)"
  ver="$(grep -E '^VERSION_ID=' "$OS_RELEASE_FILE" | cut -d= -f2 | tr -d '"' || true)"
  if [ "$id" != ubuntu ]; then
    note FAIL "not Ubuntu ($id $ver)"
  elif [ "$ver" = 24.04 ]; then
    ok "Ubuntu 24.04"
  elif [ "$(printf '%s\n24.04\n' "$ver" | sort -V | head -1)" = 24.04 ]; then
    note WARN "Ubuntu $ver is newer than the assumed 24.04 (accepted, setup log section 10)"
  else
    note FAIL "Ubuntu $ver is older than 24.04"
  fi
  finish
}
check_ram() {
  begin ram
  local kb
  kb="$(awk '/^MemTotal:/ {print $2}' "$MEMINFO_FILE")"
  if [ "${kb:-0}" -ge $((60 * GIB_KB)) ]; then ok "$((kb / GIB_KB)) GiB visible"; else note FAIL "only $((${kb:-0} / GIB_KB)) GiB visible (need >= 60)"; fi
  finish
}
check_cpu() {
  begin cpu
  local n
  n="$(nproc)"
  if [ "$n" -ge 8 ]; then ok "$n vCPU"; else note FAIL "$n vCPU (need >= 8)"; fi
  finish
}
check_disk() {
  begin disk
  local kb
  kb="$(avail_kb /)"
  if [ "${kb:-0}" -ge $((200 * GIB_KB)) ]; then ok "$((kb / GIB_KB)) GiB free on /"; else note FAIL "only $((${kb:-0} / GIB_KB)) GiB free on / (need >= 200)"; fi
  finish
}

# ---- docker (V1) ----------------------------------------------------------------------------------
check_docker() {
  begin docker
  local opts
  if ! opts="$(docker info -f '{{.SecurityOptions}}' 2>&1)"; then
    note FAIL "docker info failed without sudo (is $OWNER in group docker and logged in again?)"
  elif grep -q rootless <<<"$opts"; then
    note FAIL "Docker is rootless; the VM needs rootful Docker (Y1.3)"
  else
    ok "rootful Docker, no sudo needed"
  fi
  finish
}
check_docker_group() {
  begin docker-group
  local have want
  have="$(members_of docker)"
  want="$(printf '%s\n' pruefstand "$OWNER" | sort | tr '\n' ' ')"
  if [ "$have" = "$want" ]; then ok "members: $have"; else note FAIL "group docker is [$have], expected [$want]"; fi
  finish
}
check_docker_gw() {
  begin docker-gw
  if ip -4 addr show docker0 2>/dev/null | grep -q '172\.17\.0\.1'; then ok "docker0 has $GW"; else note FAIL "docker0 has no $GW (D242)"; fi
  finish
}
check_proxy_net() {
  begin proxy-net
  local info
  if info="$(docker network inspect proxy-egress -f '{{(index .IPAM.Config 0).Subnet}} {{.Internal}} {{index .Options "com.docker.network.bridge.name"}}' 2>/dev/null)"; then
    if [ "$info" = "10.231.0.0/24 false pfproxy0" ]; then ok "proxy-egress 10.231.0.0/24 on bridge pfproxy0, not internal"; else note FAIL "proxy-egress is [$info]"; fi
  else
    note FAIL "network proxy-egress missing (run setup-proxy-net.sh)"
  fi
  if docker network inspect demo-egress -f '{{(index .IPAM.Config 0).Subnet}}' 2>/dev/null | grep -qx '10.233.0.0/24'; then
    ok "demo-egress 10.233.0.0/24"
  else
    note WARN "network demo-egress (10.233.0.0/24) missing"
  fi
  finish
}

# ---- firewall (N4.2, D242, P2.2) ------------------------------------------------------------------
accept_before_drop() {
  local accept drop
  accept="$(grep -nE -- "-s 10\.231\.0\.0/24 .*-d 172\.17\.0\.1(/32)? .*-i pfproxy0 .*--dport 11434 .*-j ACCEPT" <<<"$1" | head -1 | cut -d: -f1 || true)"
  drop="$(grep -nE -- "^-A [A-Z-]+ -d 172\.17\.0\.1(/32)? .*--dport 11434 .*-j DROP" <<<"$1" | head -1 | cut -d: -f1 || true)"
  [ -n "$accept" ] && [ -n "$drop" ] && [ "$accept" -lt "$drop" ]
}
# Docker >= 28 replaced the DOCKER-ISOLATION-STAGE-1/2 chains by DOCKER-FORWARD/-BRIDGE/-CT/-INTERNAL; either set is fine.
chains_exist() {
  local c
  for c in "$@"; do as_root iptables -w -S "$c" >/dev/null 2>&1 || return 1; done
}
docker_chains_ok() {
  chains_exist DOCKER DOCKER-FORWARD DOCKER-BRIDGE DOCKER-CT DOCKER-INTERNAL || chains_exist DOCKER-ISOLATION-STAGE-1 DOCKER-ISOLATION-STAGE-2 DOCKER
}
fw_rules() {
  local user input net
  user="$(as_root iptables -w -S DOCKER-USER 2>&1 || true)"
  input="$(as_root iptables -w -S PRUEFSTAND-INPUT 2>&1 || true)"
  accept_before_drop "$user" || note FAIL "DOCKER-USER lacks accept(pfproxy0, 10.231.0.0/24) before drop for $GW:11434"
  grep -qE -- "-s 10\.233\.0\.0/24 .*--ctstate (RELATED,ESTABLISHED|ESTABLISHED,RELATED) .*-j RETURN" <<<"$user" ||
    note FAIL "DOCKER-USER lacks the conntrack RETURN for 10.233.0.0/24 above its drops"
  accept_before_drop "$input" || note FAIL "PRUEFSTAND-INPUT lacks accept(10.231.0.0/24) before drop for $GW:11434"
  for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16; do
    grep -qE -- "-s 10\.233\.0\.0/24 -d ${net//./\\.} -j DROP" <<<"$user" || note FAIL "DOCKER-USER lacks the drop 10.233.0.0/24 -> $net"
  done
  for net in 10.232.0.0/24 10.233.0.0/24; do
    grep -qE -- "-s ${net//./\\.} -j DROP" <<<"$input" || note FAIL "PRUEFSTAND-INPUT lacks the drop for $net"
  done
  as_root iptables -w -C INPUT -j PRUEFSTAND-INPUT >/dev/null 2>&1 || note FAIL "INPUT lacks the jump to PRUEFSTAND-INPUT"
  as_root iptables -w -S DOCKER-USER >/dev/null 2>&1 || note FAIL "Docker chain DOCKER-USER is gone"
  docker_chains_ok || note FAIL "Docker's filter chains are gone: neither the Docker >= 28 set (DOCKER, DOCKER-FORWARD, DOCKER-BRIDGE, DOCKER-CT, DOCKER-INTERNAL) nor the legacy set (DOCKER-ISOLATION-STAGE-1/2, DOCKER) is present"
  as_root iptables -w -t nat -S DOCKER >/dev/null 2>&1 || note FAIL "Docker nat chain DOCKER is gone"
}
# dcurl_state RC: reached (HTTP success) | timeout (28: what a DROP produces) | noroute (7) | dns (6) | error | other
dcurl_state() {
  case "$1" in 0) echo reached ;; 28) echo timeout ;; 7) echo noroute ;; 6) echo dns ;; 125 | 126 | 127) echo error ;; *) echo other ;; esac
}
CURL_ARGS=(-s -o /dev/null -f --connect-timeout 4 --max-time 6)
# probe_net NET URL [docker-run options...]: state of a throwaway container on NET
probe_net() {
  local net="$1" url="$2" rc=0
  shift 2
  timeout 120 docker run --rm --network "$net" "$@" --entrypoint curl "$PROBE_IMAGE" "${CURL_ARGS[@]}" "$url" >/dev/null 2>&1 || rc=$?
  dcurl_state "$rc"
}
probe_exec() {
  local rc=0
  docker exec "$1" curl "${CURL_ARGS[@]}" "$2" >/dev/null 2>&1 || rc=$?
  dcurl_state "$rc"
}
# expect WANT STATE WHAT. WANT: reached | drop (only a timeout proves a DROP) | noroute (timeout or no route).
# A DNS failure or a probe that could not run proves nothing: WARN.
expect() {
  case "$2" in
    dns) note WARN "probe inconclusive (DNS failure): $3"; return ;;
    error) note WARN "probe could not run: $3"; return ;;
  esac
  case "$1:$2" in
    reached:reached | drop:timeout | noroute:timeout | noroute:noroute) ;;
    *) note FAIL "$3 (wanted $1, got $2)" ;;
  esac
}
fw_gateway_probes() {
  local tmp="pf-probe-int-$$"
  expect reached "$(probe_net proxy-egress "http://$GW:11434/api/tags")" "proxy-egress container -> $GW:11434"
  expect drop "$(probe_net bridge "http://$GW:11434/api/tags")" "default bridge container -> $GW:11434"
  if docker network create --internal "$tmp" >/dev/null 2>&1; then
    PROBE_NETS+=("$tmp")
    expect noroute "$(probe_net "$tmp" https://1.1.1.1/)" "--internal network container -> internet"
  fi
}
# cluster_endpoint: resolve the SSH endpoint; a public address cannot be blocked by RFC 1918 rules
cluster_endpoint() {
  local host port ip
  host="$(as_pf ssh -G cairo-s101lp 2>/dev/null | awk '$1=="hostname" {print $2}' || true)"
  port="$(as_pf ssh -G cairo-s101lp 2>/dev/null | awk '$1=="port" {print $2}' || true)"
  [ -n "$host" ] || return 0
  ip="$(getent ahostsv4 "$host" 2>/dev/null | awk 'NR==1 {print $1}' || true)"
  if [[ "$ip" =~ ^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.) ]]; then
    CLUSTER_ENDPOINT="$ip|${port:-22}"
  else
    note WARN "cluster endpoint is public; not blockable by RFC1918 rules"
  fi
}
# targets the demo containers must never reach: "label|host|port"
demo_targets() {
  local port lan
  if [ -n "${TRUENAS_HOST_IP:-}" ]; then
    for port in 2049 445 443 80; do echo "truenas-$port|$TRUENAS_HOST_IP|$port"; done
  fi
  if [ -n "$CLUSTER_ENDPOINT" ]; then echo "cluster-ssh|${CLUSTER_ENDPOINT%|*}|${CLUSTER_ENDPOINT#*|}"; fi
  lan="$(hostname -I | tr ' ' '\n' | grep -vE '^(172\.17\.|10\.23[0-9]\.)' | head -1 || true)"
  if [ -n "$lan" ]; then echo "vm-lan|$lan|22"; fi
}
fw_demo_probes() {
  local net=demo-net cf="pf-probe-cf-$$" label host port
  cluster_endpoint
  if ! docker network inspect demo-net >/dev/null 2>&1; then
    net="pf-probe-demo-$$"
    if docker network create --internal --subnet 10.232.0.0/24 "$net" >/dev/null 2>&1; then PROBE_NETS+=("$net"); fi
  fi
  expect noroute "$(probe_net "$net" https://1.1.1.1/)" "demo-net container -> internet"
  while IFS='|' read -r label host port; do
    expect noroute "$(probe_net "$net" "http://$host:$port/")" "demo-net container -> $label"
  done < <(demo_targets)
  PROBE_CONTAINERS+=("$cf")
  if docker run -d --name "$cf" --network "$net" --ip 10.232.0.2 --entrypoint sleep "$PROBE_IMAGE" 120 >/dev/null 2>&1 &&
    docker network connect demo-egress "$cf" >/dev/null 2>&1; then
    if ! docker exec "$cf" nslookup example.com >/dev/null 2>&1; then
      note WARN "a demo-egress container cannot resolve names; set dns: (e.g. 1.1.1.1) on the cloudflared service"
    fi
    expect reached "$(probe_exec "$cf" https://example.com)" "cloudflared-like container -> internet"
    while IFS='|' read -r label host port; do
      expect drop "$(probe_exec "$cf" "http://$host:$port/")" "cloudflared-like container -> $label"
    done < <(demo_targets)
  else
    note WARN "cloudflared-like probe container could not start (10.232.0.2 in use or image missing)"
  fi
}
check_firewall() {
  begin firewall
  if [ "$(systemctl is-active pruefstand-firewall 2>/dev/null || true)" != active ]; then note FAIL "pruefstand-firewall.service is not active"; fi
  if [ "$(systemctl is-enabled nftables 2>/dev/null || true)" = enabled ]; then note FAIL "the nftables unit is enabled (it would reload a ruleset over Docker's)"; fi
  [ -z "$EXTRA_FW_NOTE" ] || note FAIL "$EXTRA_FW_NOTE"
  case "$PROBE_IMAGE" in *@sha256:*) ;; *) note WARN "PROBE_IMAGE is a tag, not a digest; pin it: PROBE_IMAGE=curlimages/curl@sha256:..." ;; esac
  if have_sudo; then fw_rules; else note WARN "iptables rules not checked: run 'sudo -v' first"; fi
  fw_gateway_probes
  fw_demo_probes
  [ "${#NOTES[@]}" -gt 0 ] || ok "rules in place, Docker chains intact, gateway and demo probes as expected"
  finish
}

# ---- GitHub token (N4.4) --------------------------------------------------------------------------
check_gh_scope() {
  begin gh-scope
  local tok out rc=0
  tok="$(timeout 30 gh auth token 2>/dev/null || true)"
  case "$tok" in github_pat_*) ok "fine-grained token" ;; *) note FAIL "gh token is not a fine-grained github_pat_ token" ;; esac
  tok=""
  # permissions.admin of GET /repos/{repo} is the owner's role, not the token's rights. Probe the token itself:
  # an administration-only endpoint must answer 403 "Resource not accessible by personal access token".
  out="$(timeout 30 gh api "repos/$PUBLIC_REPO/actions/permissions" 2>&1)" || rc=$?
  if [ "$rc" -eq 0 ]; then
    note FAIL "the token has administration rights on $PUBLIC_REPO (actions/permissions answered 200); use a token without them"
  elif grep -q 'HTTP 403' <<<"$out" && grep -q 'Resource not accessible by personal access token' <<<"$out"; then
    ok "no administration right on $PUBLIC_REPO (actions/permissions -> 403)"
  else
    note WARN "could not tell whether the token has administration rights on $PUBLIC_REPO (rc $rc; no network?)"
  fi
  if out="$(timeout 30 gh api "repos/$GATE_REPO" 2>&1)"; then
    note FAIL "the token can read $GATE_REPO (must be 404, C18)"
  elif grep -q 'HTTP 404' <<<"$out"; then
    ok "$GATE_REPO -> 404"
  else
    note WARN "could not tell whether $GATE_REPO is hidden (no network?)"
  fi
  finish
}

# ---- users, lock, data root, key (V2, V4, V5) -----------------------------------------------------
check_users() {
  begin users
  getent passwd pruefstand >/dev/null || note FAIL "user pruefstand missing (setup-users.sh)"
  case " $(members_of pruefstand)" in *" $OWNER "*) ok "$OWNER is in group pruefstand" ;; *) note FAIL "$OWNER not in group pruefstand (log in again after setup-users.sh)" ;; esac
  finish
}
check_lock_dir() {
  begin lock-dir
  local dir_state lock_state
  dir_state="$(stat -c '%a %U:%G' "$LOCK_DIR" 2>&1 || true)"
  lock_state="$(stat -c '%a %U:%G' "$LOCK_DIR/gpu.lock" 2>&1 || true)"
  [ "$dir_state" = "2770 pruefstand:pruefstand" ] || note FAIL "$LOCK_DIR is [$dir_state], expected 2770 pruefstand:pruefstand"
  [ "$lock_state" = "660 pruefstand:pruefstand" ] || note FAIL "gpu.lock is [$lock_state], expected 660 pruefstand:pruefstand"
  local lock_rc=0
  GPU_LOCK_TIMEOUT_S=10 pruefstand-lock true >/dev/null 2>&1 || lock_rc=$?
  case "$lock_rc" in
    0) ok "pruefstand-lock true works" ;;
    75) note WARN "gpu.lock busy: a job or another command holds the GPU lock" ;;
    *) note FAIL "pruefstand-lock true failed (rc $lock_rc); is $OWNER in group pruefstand (log in again)?" ;;
  esac
  if [ -e "$LOCK_DIR/MAINTENANCE" ]; then note WARN "maintenance set ($LOCK_DIR/MAINTENANCE exists; clear with rm when the swap is done)"; fi
  finish
}
check_data_root() {
  begin data-root
  local kb
  [ -d "$DATA_ROOT" ] || note FAIL "$DATA_ROOT is not a directory"
  [ "$(findmnt -no TARGET -T "$DATA_ROOT" 2>/dev/null || true)" = / ] || note FAIL "$DATA_ROOT is not on the root disk (ADR-0019: plain directory)"
  [ -f "$DATA_ROOT/.pruefstand-data-root" ] || note FAIL "sentinel $DATA_ROOT/.pruefstand-data-root missing"
  [ "$(stat -c %U "$DATA_ROOT" 2>/dev/null || true)" = pruefstand ] || note FAIL "$DATA_ROOT is not owned by pruefstand"
  if grep -qE "[[:space:]]${DATA_ROOT}[[:space:]]" "$FSTAB_FILE" 2>/dev/null; then note FAIL "$FSTAB_FILE has a line for $DATA_ROOT (ADR-0019: no mount)"; fi
  kb="$(avail_kb "$DATA_ROOT")"
  if [ "${kb:-0}" -lt $((20 * GIB_KB)) ]; then note WARN "only $((${kb:-0} / GIB_KB)) GiB free under $DATA_ROOT (need >= 20)"; fi
  [ "${#NOTES[@]}" -gt 0 ] || ok "plain directory, sentinel present, $((kb / GIB_KB)) GiB free"
  finish
}
check_data_root_rw() {
  begin data-root-rw
  # shellcheck disable=SC2016  # the snippet is expanded by the inner sh, not here
  if as_pf sh -c 'f=$(mktemp "$1/cache/.probe.XXXXXX") && mv "$f" "$f.r" && rm "$f.r"' _ "$DATA_ROOT" 2>/dev/null; then
    ok "pruefstand can write, rename and delete in $DATA_ROOT/cache"
  else
    note FAIL "pruefstand cannot write in $DATA_ROOT/cache (or sudo needs a password: sudo -v)"
  fi
  finish
}
check_ssh_key() {
  begin ssh-key
  local home
  if as_pf ssh -o BatchMode=yes -o PreferredAuthentications=publickey -o ConnectTimeout=15 cairo-s101lp true >/dev/null 2>&1; then
    ok "pruefstand logs in to cairo-s101lp by key"
  else
    note FAIL "BatchMode ssh to cairo-s101lp as pruefstand failed (setup-ssh-key.sh prints the ssh-copy-id line)"
  fi
  home="$(getent passwd "$OWNER" | cut -d: -f6)"
  if compgen -G "$home/.ssh/id_ed25519_cluster*" >/dev/null; then note FAIL "cluster key copy in $home/.ssh (the owner must not hold it)"; fi
  finish
}

# ---- tunnel (V3, ADR-0018) ------------------------------------------------------------------------
tunnel_listeners() {
  local listen addr
  if have_sudo; then listen="$(as_root ss -ltnpH 2>/dev/null || true)"; else listen="$(ss -ltnpH 2>/dev/null || true)"; fi
  for addr in 127.0.0.1:11434 $GW:11434; do
    awk '{print $4}' <<<"$listen" | grep -qx "$addr" || note FAIL "no listener on $addr"
  done
  if awk '{print $4}' <<<"$listen" | grep -E ':11434$' | grep -vxE "127\.0\.0\.1:11434|172\.17\.0\.1:11434" | grep -q .; then
    note FAIL "port 11434 is also bound on another address (never 0.0.0.0 or the LAN address)"
  fi
  if grep -E '"(auto)?ssh"' <<<"$listen" | awk '{print $4}' | grep -vE ':11434$' | grep -q .; then
    note WARN "ssh listens on a port other than 11434 (temporary forward left open?)"
  fi
  if systemctl cat pruefstand-tunnel 2>/dev/null | grep -oE -- '-L [^ ]+' | grep -vE ':11434:localhost:11434$' | grep -q .; then
    note WARN "the unit forwards a port other than 11434 (ADR-0018)"
  fi
}
tunnel_env() {
  local g0 g1
  g0="$(envval OLLAMA_GPU0_URL)"
  g1="$(envval OLLAMA_GPU1_URL)"
  if [ -z "$g0" ]; then note WARN "OLLAMA_GPU0_URL not found in $ENV_FILE"; fi
  if grep -E '^https?://' <<<"$g0"$'\n'"$g1" | grep -vqE '^https?://(127\.0\.0\.1|localhost)[:/]'; then
    note FAIL "an OLLAMA_GPU*_URL is not a loopback address; no public tunnel may be used (C19)"
  elif [ -n "$g0" ] && [ "$g0" != http://127.0.0.1:11434 ]; then note WARN "OLLAMA_GPU0_URL is [$(redact <<<"$g0")], expected http://127.0.0.1:11434"; fi
  if [ "$g1" != "$g0" ]; then note WARN "OLLAMA_GPU1_URL [$(redact <<<"$g1")] differs from OLLAMA_GPU0_URL [$(redact <<<"$g0")] (one server, ADR-0018)"; fi
}
check_tunnel() {
  begin tunnel
  local user frag code
  [ "$(systemctl is-active pruefstand-tunnel 2>/dev/null || true)" = active ] || note FAIL "pruefstand-tunnel.service is not active"
  user="$(systemctl show -p User --value pruefstand-tunnel 2>/dev/null || true)"
  frag="$(systemctl show -p FragmentPath --value pruefstand-tunnel 2>/dev/null || true)"
  [ "$user" = pruefstand ] || note FAIL "tunnel unit runs as [$user], expected a system unit with User=pruefstand"
  case "$frag" in /home/* | */.config/systemd/user/*) note FAIL "tunnel unit is a user unit ($frag)" ;; esac
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:11434/api/tags 2>/dev/null || true)"
  [ "$code" = 200 ] || note FAIL "127.0.0.1:11434/api/tags answered [$code]"
  tunnel_listeners
  tunnel_env
  [ "${#NOTES[@]}" -gt 0 ] || ok "system unit as pruefstand, /api/tags 200, 11434 only on 127.0.0.1 and $GW"
  finish
}

# ---- owner-confirmed checks -----------------------------------------------------------------------
confirmed() {
  begin "$1"
  if grep -q "^$1 " "$CONFIRM_FILE" 2>/dev/null; then ok "confirmed by owner: $(grep "^$1 " "$CONFIRM_FILE" | tail -1 | cut -d' ' -f2-)"; else note WARN "$2; then run: vm_check.sh --confirm $1"; fi
  finish
}
check_tunnel_reboot() { confirmed tunnel-reboot "reboot the VM once and check that the tunnel is active without manual steps"; }
check_host_reboot() { confirmed host-reboot "reboot the TrueNAS host once; the VM, data root and tunnel must come back alone"; }
check_vscode() { confirmed vscode "open the VM from Windows VS Code (Remote-SSH) and run make check there"; }

restart_drill() {
  local limit="${DRILL_WAIT_S:-90}" waited=0 before after
  exec 9<"$LOCK_DIR/gpu.lock"
  if ! flock -n 9; then
    echo "vm_check: gpu.lock busy; a gate or nightly may be running, not touching Docker" >&2
    exit 75
  fi
  if [ "$YES" -ne 1 ] && [ -n "$(docker ps -q 2>/dev/null || true)" ]; then
    echo "vm_check: running containers would be stopped by the restart; stop them or pass --yes" >&2
    exit 2
  fi
  before="$(systemctl show -p ActiveEnterTimestampMonotonic --value pruefstand-firewall 2>/dev/null || true)"
  as_root systemctl restart docker
  until docker info >/dev/null 2>&1 && [ "$(systemctl is-active pruefstand-firewall 2>/dev/null || true)" = active ]; do
    [ "$waited" -lt "$limit" ] || break
    sleep 2
    waited=$((waited + 2))
  done
  after="$(systemctl show -p ActiveEnterTimestampMonotonic --value pruefstand-firewall 2>/dev/null || true)"
  if [ -z "$after" ] || [ "$after" = "$before" ]; then EXTRA_FW_NOTE="pruefstand-firewall.service did not restart with Docker (PartOf=)"; fi
  check_firewall
  exit $((FAILS > 0))
}

# ---- main -----------------------------------------------------------------------------------------
WANT=()
DRILL=0
YES=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --owner) OWNER="$2"; shift 2 ;;
    --restart-drill) DRILL=1; shift ;;
    --yes) YES=1; shift ;;
    --strict) STRICT=1; shift ;;
    --confirm)
      case "$2" in tunnel-reboot | host-reboot | vscode) ;; *) echo "can only confirm: tunnel-reboot host-reboot vscode" >&2; exit 2 ;; esac
      mkdir -p "$(dirname "$CONFIRM_FILE")"
      echo "$2 $(date -u +%Y-%m-%dT%H:%MZ)" >>"$CONFIRM_FILE"
      echo "recorded $2"
      exit 0
      ;;
    -h | --help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) WANT+=("$1"); shift ;;
  esac
done
if [ "$(id -u)" -eq 0 ] && [ -z "${PRUEFSTAND_ALLOW_ROOT:-}" ]; then
  echo "vm_check: run it as the owner user, not as root (it uses sudo -n where needed)" >&2
  exit 2
fi
[ "$DRILL" -eq 0 ] || restart_drill

run_check() {
  case "$1" in
    os) check_os ;; ram) check_ram ;; cpu) check_cpu ;; disk) check_disk ;; docker) check_docker ;;
    docker-group) check_docker_group ;; docker-gw) check_docker_gw ;; proxy-net) check_proxy_net ;;
    firewall) check_firewall ;; gh-scope) check_gh_scope ;; users) check_users ;; lock-dir) check_lock_dir ;;
    data-root) check_data_root ;; data-root-rw) check_data_root_rw ;; ssh-key) check_ssh_key ;;
    tunnel) check_tunnel ;; tunnel-reboot) check_tunnel_reboot ;; host-reboot) check_host_reboot ;;
    vscode) check_vscode ;;
    *) echo "unknown check id: $1" >&2; exit 2 ;;
  esac
}

for id in "${WANT[@]}"; do
  [[ " ${ALL_IDS[*]} " == *" $id "* ]] || { echo "unknown check id: $id" >&2; exit 2; }
done
for id in "${ALL_IDS[@]}"; do
  if [ "${#WANT[@]}" -eq 0 ] || [[ " ${WANT[*]} " == *" $id "* ]]; then
    run_check "$id"
  fi
done
exit $((FAILS > 0))
