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
# Gateway rules first: the gateway pair, the PRUEFSTAND-INPUT chain and its jump are installed BEFORE the demo-subnet
# gate (route guard) is evaluated; a failing guard exits 3 only after the gateway drop is in place.
# Options: --dry-run (print "PLAN ..." for every change),
#          --check (exit 1 if a rule is missing or misordered; exit 3 if all gateway rules are fine but the demo gate is closed),
#          --check-gateway (exit 1 unless the INPUT jump and the gateway accept-before-drop pair exist in
#          PRUEFSTAND-INPUT and DOCKER-USER; used as ExecStartPre of pruefstand-tunnel.service, fail closed).
set -euo pipefail

GW=172.17.0.1
PORT=11434
INPUT_CHAIN=PRUEFSTAND-INPUT
DRY=0
CHECK=0
CHECK_GW=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --check) CHECK=1; shift ;;
    --check-gateway) CHECK_GW=1; CHECK=1; shift ;;
    -h | --help) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

BRIDGE=pfproxy0
GW_ACCEPT="-i $BRIDGE -s 10.231.0.0/24 -d $GW -p tcp --dport $PORT -j ACCEPT"
LEGACY_ACCEPT="-s 10.231.0.0/24 -d $GW -p tcp --dport $PORT -j ACCEPT"
GW_DROP="-d $GW -p tcp --dport $PORT -j DROP"
CT_DEMO="-s 10.233.0.0/24 -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN"
GW_USER_RULES=("$GW_ACCEPT" "$GW_DROP")
GW_INPUT_RULES=("$GW_ACCEPT" "$GW_DROP")
DEMO_USER_RULES=(
  "$CT_DEMO"
  "-s 10.233.0.0/24 -d 10.0.0.0/8 -j DROP"
  "-s 10.233.0.0/24 -d 172.16.0.0/12 -j DROP"
  "-s 10.233.0.0/24 -d 192.168.0.0/16 -j DROP"
)
DEMO_INPUT_RULES=(
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
# foreign_routes: return 1 (with a message) when a route of anything but a Docker bridge overlaps a demo subnet:
# Docker's bridge route would be shadowed and could cut SSH. Only the demo rules wait for this gate.
foreign_routes() {
  command -v ip >/dev/null || return 0
  local subnet route rest
  while read -r route rest; do
    case "$route" in
      default) continue ;;
      blackhole | unreachable | prohibit | throw) read -r route rest <<<"$rest" ;;
    esac
    [[ "$route" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(/[0-9]+)?$ ]] || continue
    case " $rest " in *" dev docker0 "* | *" dev br-"* | *" dev pfproxy0 "*) continue ;; esac
    case "$route" in */*) ;; *) route="$route/32" ;; esac
    for subnet in 10.232.0.0/24 10.233.0.0/24; do
      if overlaps "$subnet" "$route"; then
        echo "pruefstand-firewall: route $route overlaps $subnet; Docker's bridge route would shadow it and could cut SSH. Fix the route first. Demo rules NOT installed." >&2
        return 1
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
  accept="$(grep -nE -- "-s 10\.231\.0\.0/24 .*-d 172\.17\.0\.1(/32)? .*-i pfproxy0 .*--dport 11434 .*-j ACCEPT" <<<"$listing" | head -1 | cut -d: -f1 || true)"
  drop="$(grep -nE -- "^-A [A-Z-]+ -d 172\.17\.0\.1(/32)? .*--dport 11434 .*-j DROP" <<<"$listing" | head -1 | cut -d: -f1 || true)"
  [ -n "$accept" ] && [ -n "$drop" ] && [ "$accept" -lt "$drop" ]
}
DEMO_OK=1
foreign_routes || DEMO_OK=0
DOCKER_USER_RULES=("${GW_USER_RULES[@]}")
INPUT_RULES=("${GW_INPUT_RULES[@]}")
if [ "$DEMO_OK" -eq 1 ]; then
  DOCKER_USER_RULES+=("${DEMO_USER_RULES[@]}")
  INPUT_RULES+=("${DEMO_INPUT_RULES[@]}")
fi

# jump_first: the very first rule of INPUT is the jump to our chain
jump_first() {
  [ "$(ipt -S INPUT 2>/dev/null | grep '^-A' | head -1 || true)" = "-A INPUT -j $INPUT_CHAIN" ]
}
# jump_number: line number (among -A rules) of an existing jump to our chain, empty when absent
jump_number() {
  ipt -S INPUT 2>/dev/null | grep '^-A' | grep -nxF -- "-A INPUT -j $INPUT_CHAIN" | head -1 | cut -d: -f1 || true
}
# problems: print every missing rule / wrong order
problems() {
  missing DOCKER-USER "${DOCKER_USER_RULES[@]}"
  missing "$INPUT_CHAIN" "${INPUT_RULES[@]}"
  jump_first || echo "INPUT: -j $INPUT_CHAIN is missing or not the first rule (a rule ahead of it, e.g. ufw, can accept first)"
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

if [ "$CHECK_GW" -eq 1 ]; then
  DOCKER_USER_RULES=("${GW_USER_RULES[@]}")
  INPUT_RULES=("${GW_INPUT_RULES[@]}")
fi
if [ "$CHECK" -eq 1 ]; then
  gone="$(problems | sed '/^$/d')"
  if [ -n "$gone" ]; then echo "missing or wrong rules:"; echo "$gone"; exit 1; fi
  if [ "$CHECK_GW" -eq 0 ] && [ "$DEMO_OK" -eq 0 ]; then
    echo "gateway rules present, in order; demo rules not checked (route guard closed)"
    exit 3
  fi
  echo "all Pruefstand firewall rules present, in order"
  exit 0
fi

changes=0
# a legacy accept without the bridge match (older version of this script) is removed; idempotent
if have DOCKER-USER "$LEGACY_ACCEPT"; then
  read -r -a legacy_args <<<"$LEGACY_ACCEPT"
  run -D DOCKER-USER "${legacy_args[@]}"
  changes=1
fi
legacy_in_input=0
if have "$INPUT_CHAIN" "$LEGACY_ACCEPT"; then legacy_in_input=1; fi
docker_user_needs="$(missing DOCKER-USER "${DOCKER_USER_RULES[@]}")"
if [ -n "$docker_user_needs" ] || ! gw_order_ok DOCKER-USER; then changes=1; fi
input_needs="$(missing "$INPUT_CHAIN" "${INPUT_RULES[@]}")"
if [ "$legacy_in_input" -eq 1 ] || [ -n "$input_needs" ] || ! ipt -L "$INPUT_CHAIN" -n >/dev/null 2>&1 || ! gw_order_ok "$INPUT_CHAIN"; then
  input_apply
  changes=1
fi
if ! jump_first; then
  old="$(jump_number)"
  run -I INPUT 1 -j "$INPUT_CHAIN"
  if [ -n "$old" ]; then run -D INPUT "$((old + 1))"; fi
  changes=1
fi
docker_user_apply
if [ "$DEMO_OK" -eq 0 ]; then exit 3; fi
if [ "$changes" -eq 0 ]; then echo "no changes needed"; fi
