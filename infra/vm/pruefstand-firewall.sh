#!/usr/bin/env bash
# pruefstand-firewall.sh: the Pruefstand packet-filter rules (D242, R12 N4.2/D285, R13 P2.2/D320).
#
# Installed to /usr/local/sbin by setup-proxy-net.sh and run by pruefstand-firewall.service after every
# Docker (re)start. It touches ONLY its own chain PRUEFSTAND-INPUT, one jump from INPUT and its own rules
# in Docker's DOCKER-USER. It never flushes the ruleset, never loads nft files, never touches nat/mangle or
# the distro nftables service (that would delete Docker's NAT and --internal drop rules, A12-02).
#   * 172.17.0.1:11434 (the tunnel on the Docker bridge gateway) is reachable only from proxy-egress
#     10.231.0.0/24; everyone else is dropped. Container -> host traffic is delivered locally and passes
#     INPUT, not FORWARD, so the same pair is in both chains (D285).
#   * demo-egress 10.233.0.0/24 (cloudflared's internet side) gets no RFC 1918 destination (LAN, TrueNAS,
#     cluster SSH, other Docker networks) and no VM address (PRUEFSTAND-INPUT drop); demo-net 10.232.0.0/24
#     is --internal (no egress) and only gets the INPUT drop for the VM's own addresses.
# Options: --dry-run (print "PLAN ..." for every change), --check (exit 1 if a rule is missing).
set -euo pipefail

GW=172.17.0.1
PORT=11434
INPUT_CHAIN=PRUEFSTAND-INPUT
DRY=0
CHECK=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --check) CHECK=1; shift ;;
    -h | --help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ "$DRY" -eq 0 ] && [ "$CHECK" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
  echo "pruefstand-firewall: needs root (sudo), or use --dry-run" >&2
  exit 2
fi

ipt() { iptables -w "$@"; }
run() {
  if [ "$DRY" -eq 1 ]; then echo "PLAN iptables -w $*"; else echo "DO   iptables -w $*"; ipt "$@"; fi
}

DOCKER_USER_RULES=(
  "-s 10.231.0.0/24 -d $GW -p tcp --dport $PORT -j ACCEPT"
  "-d $GW -p tcp --dport $PORT -j DROP"
  "-s 10.233.0.0/24 -d 10.0.0.0/8 -j DROP"
  "-s 10.233.0.0/24 -d 172.16.0.0/12 -j DROP"
  "-s 10.233.0.0/24 -d 192.168.0.0/16 -j DROP"
)
INPUT_RULES=(
  "-s 10.231.0.0/24 -d $GW -p tcp --dport $PORT -j ACCEPT"
  "-d $GW -p tcp --dport $PORT -j DROP"
  "-s 10.232.0.0/24 -j DROP"
  "-s 10.233.0.0/24 -j DROP"
)

# have CHAIN RULE: does the rule exist?
have() {
  local -a args
  read -r -a args <<<"$2"
  ipt -C "$1" "${args[@]}" 2>/dev/null
}

# missing CHAIN RULES...: print the rules that are absent.
missing() {
  local chain="$1" rule
  shift
  for rule in "$@"; do
    have "$chain" "$rule" || echo "$chain: $rule"
  done
}

# ensure_block CHAIN MODE RULES...: if any rule is absent, re-create all of them in order.
#   MODE=insert: remove our present rules from the shared chain, then insert at positions 1..n
#   MODE=append: our own chain was flushed before, append in order
ensure_block() {
  local chain="$1" mode="$2" rule pos=1
  local -a args
  shift 2
  [ -n "$(missing "$chain" "$@")" ] || return 0
  if [ "$mode" = insert ]; then
    for rule in "$@"; do
      read -r -a args <<<"$rule"
      if have "$chain" "$rule"; then run -D "$chain" "${args[@]}"; fi
    done
  else
    run -F "$chain"
  fi
  for rule in "$@"; do
    read -r -a args <<<"$rule"
    if [ "$mode" = insert ]; then run -I "$chain" "$pos" "${args[@]}"; else run -A "$chain" "${args[@]}"; fi
    pos=$((pos + 1))
  done
}

if [ "$CHECK" -eq 1 ]; then
  gone="$(missing DOCKER-USER "${DOCKER_USER_RULES[@]}"; missing "$INPUT_CHAIN" "${INPUT_RULES[@]}")"
  ipt -C INPUT -j "$INPUT_CHAIN" 2>/dev/null || gone+=$'\nINPUT: -j '"$INPUT_CHAIN"
  gone="$(sed '/^$/d' <<<"$gone")"
  if [ -n "$gone" ]; then echo "missing rules:"; echo "$gone"; exit 1; fi
  echo "all Pruefstand firewall rules present"
  exit 0
fi

changes=0
ipt -L "$INPUT_CHAIN" -n >/dev/null 2>&1 || { run -N "$INPUT_CHAIN"; changes=1; }
if ! ipt -C INPUT -j "$INPUT_CHAIN" 2>/dev/null; then run -I INPUT 1 -j "$INPUT_CHAIN"; changes=1; fi
before="$(missing DOCKER-USER "${DOCKER_USER_RULES[@]}"; missing "$INPUT_CHAIN" "${INPUT_RULES[@]}")"
ensure_block DOCKER-USER insert "${DOCKER_USER_RULES[@]}"
ensure_block "$INPUT_CHAIN" append "${INPUT_RULES[@]}"
if [ "$changes" -eq 0 ] && [ -z "$before" ]; then echo "no changes needed"; fi
