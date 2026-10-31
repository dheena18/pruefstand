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
#   * no rule is ever removed before its replacement exists: the DOCKER-USER rules are inserted (drop first, then
#     accept above it), PRUEFSTAND-INPUT is replaced in ONE iptables-restore --noflush transaction. Replies to
#     connections the VM itself opened to the demo networks are let through (conntrack RETURN) before their drops.
#   * aborts (exit 3) when a non-Docker route overlaps 10.232.0.0/24 or 10.233.0.0/24: Docker's bridge route would
#     shadow it and could cut SSH.
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
    -h | --help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

GW_ACCEPT="-s 10.231.0.0/24 -d $GW -p tcp --dport $PORT -j ACCEPT"
GW_DROP="-d $GW -p tcp --dport $PORT -j DROP"
DOCKER_USER_RULES=(
  "$GW_ACCEPT"
  "$GW_DROP"
  "-s 10.233.0.0/24 -d 10.0.0.0/8 -j DROP"
  "-s 10.233.0.0/24 -d 172.16.0.0/12 -j DROP"
  "-s 10.233.0.0/24 -d 192.168.0.0/16 -j DROP"
)
INPUT_RULES=(
  "$GW_ACCEPT"
  "$GW_DROP"
  "-m conntrack --ctstate ESTABLISHED,RELATED -j RETURN"
  "-s 10.232.0.0/24 -j DROP"
  "-s 10.233.0.0/24 -j DROP"
)

ip2int() {
  local IFS=. a b c d
  read -r a b c d <<<"$1"
  echo $(((a << 24) | (b << 16) | (c << 8) | d))
}
overlaps() {
  local p1="${1#*/}" p2="${2#*/}" prefix mask
  prefix=$((p1 < p2 ? p1 : p2))
  mask=$((prefix == 0 ? 0 : (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF))
  [ $(($(ip2int "${1%/*}") & mask)) -eq $(($(ip2int "${2%/*}") & mask)) ]
}
# refuse_foreign_routes: a route of anything but a Docker bridge overlapping a demo subnet would be shadowed
refuse_foreign_routes() {
  command -v ip >/dev/null || return 0
  local subnet route rest
  while read -r route rest; do
    case "$route" in
      default) continue ;;
      blackhole | unreachable | prohibit | throw) read -r route rest <<<"$rest" ;;
    esac
    [[ "$route" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(/[0-9]+)?$ ]] || continue
    case " $rest " in *" dev docker0 "* | *" dev br-"*) continue ;; esac
    case "$route" in */*) ;; *) route="$route/32" ;; esac
    for subnet in 10.232.0.0/24 10.233.0.0/24; do
      if overlaps "$subnet" "$route"; then
        echo "pruefstand-firewall: route $route overlaps $subnet; Docker's bridge route would shadow it and could cut SSH. Fix the route first." >&2
        exit 3
      fi
    done
  done < <(ip -4 route show)
}

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
# gw_order_ok CHAIN: the accept for 10.231.0.0/24 stands before the drop for the gateway port
gw_order_ok() {
  local listing accept drop
  listing="$(ipt -S "$1" 2>/dev/null || true)"
  accept="$(grep -nE -- "-s 10\.231\.0\.0/24 .*-d 172\.17\.0\.1(/32)? .*--dport 11434 .*-j ACCEPT" <<<"$listing" | head -1 | cut -d: -f1 || true)"
  drop="$(grep -nE -- "^-A [A-Z-]+ -d 172\.17\.0\.1(/32)? .*--dport 11434 .*-j DROP" <<<"$listing" | head -1 | cut -d: -f1 || true)"
  [ -n "$accept" ] && [ -n "$drop" ] && [ "$accept" -lt "$drop" ]
}
# problems: print every missing rule / wrong order
problems() {
  missing DOCKER-USER "${DOCKER_USER_RULES[@]}"
  missing "$INPUT_CHAIN" "${INPUT_RULES[@]}"
  ipt -C INPUT -j "$INPUT_CHAIN" 2>/dev/null || echo "INPUT: -j $INPUT_CHAIN (jump missing)"
  gw_order_ok DOCKER-USER || echo "DOCKER-USER: wrong order (accept must stand before the drop)"
  gw_order_ok "$INPUT_CHAIN" || echo "$INPUT_CHAIN: wrong order (accept must stand before the drop)"
}

# docker_user_apply: insert what is missing, drop first and accept above it; fix a wrong order by inserting a
# fresh accept above and deleting the old one by number. The drop is never removed.
docker_user_apply() {
  local i rule listing num
  local -a args
  for ((i = ${#DOCKER_USER_RULES[@]} - 1; i >= 0; i--)); do
    rule="${DOCKER_USER_RULES[$i]}"
    read -r -a args <<<"$rule"
    have DOCKER-USER "$rule" || run -I DOCKER-USER 1 "${args[@]}"
  done
  if have DOCKER-USER "$GW_ACCEPT" && ! gw_order_ok DOCKER-USER && [ -z "$(missing DOCKER-USER "$GW_DROP")" ]; then
    read -r -a args <<<"$GW_ACCEPT"
    listing="$(ipt -S DOCKER-USER 2>/dev/null | grep '^-A' || true)"
    num="$(grep -nE -- "-s 10\.231\.0\.0/24 .*--dport 11434 .*-j ACCEPT" <<<"$listing" | tail -1 | cut -d: -f1)"
    run -I DOCKER-USER 1 "${args[@]}"
    run -D DOCKER-USER "$((num + 1))"
  fi
}

# input_apply: one iptables-restore --noflush transaction replaces the chain contents atomically
input_apply() {
  local rule
  if [ "$DRY" -eq 1 ]; then
    echo "PLAN iptables-restore --noflush :$INPUT_CHAIN (declared again: contents replaced in one transaction)"
    for rule in "${INPUT_RULES[@]}"; do echo "PLAN iptables-restore --noflush -A $INPUT_CHAIN $rule"; done
    return
  fi
  echo "DO   iptables-restore --noflush (chain $INPUT_CHAIN)"
  {
    printf '*filter\n:%s - [0:0]\n' "$INPUT_CHAIN"
    for rule in "${INPUT_RULES[@]}"; do printf -- '-A %s %s\n' "$INPUT_CHAIN" "$rule"; done
    printf 'COMMIT\n'
  } | iptables-restore -w --noflush
}

refuse_foreign_routes
if [ "$CHECK" -eq 1 ]; then
  gone="$(problems | sed '/^$/d')"
  if [ -n "$gone" ]; then echo "missing or wrong rules:"; echo "$gone"; exit 1; fi
  echo "all Pruefstand firewall rules present, in order"
  exit 0
fi

changes=0
docker_user_needs="$(missing DOCKER-USER "${DOCKER_USER_RULES[@]}")"
if [ -n "$docker_user_needs" ] || ! gw_order_ok DOCKER-USER; then changes=1; fi
input_needs="$(missing "$INPUT_CHAIN" "${INPUT_RULES[@]}")"
if [ -n "$input_needs" ] || ! ipt -L "$INPUT_CHAIN" -n >/dev/null 2>&1 || ! gw_order_ok "$INPUT_CHAIN"; then
  input_apply
  changes=1
fi
if ! ipt -C INPUT -j "$INPUT_CHAIN" 2>/dev/null; then
  run -I INPUT 1 -j "$INPUT_CHAIN"
  changes=1
fi
docker_user_apply
if [ "$changes" -eq 0 ]; then echo "no changes needed"; fi
