#!/usr/bin/env bash
# setup-proxy-net.sh: Docker egress networks and the firewall unit (S5b, D242, R12 N4.2, R13 P2.2).
#
# Run once by the owner: sudo infra/vm/setup-proxy-net.sh [--dry-run]   (idempotent)
#   * docker network create --driver bridge --subnet 10.231.0.0/24 proxy-egress   (llm-proxy -> tunnel)
#   * docker network create --driver bridge --subnet 10.233.0.0/24 demo-egress    (cloudflared's internet side)
#     (demo-net 10.232.0.0/24 is created --internal by the demo compose file, T8.4/T8.5, not here)
#     A network is only created if missing; a subnet that clashes with an existing route is refused (exit 3).
#   * installs pruefstand-firewall.sh to /usr/local/sbin and pruefstand-firewall.service, then enables and
#     (re)starts the oneshot unit, which applies the rules after every Docker start
# Options: --dry-run  --bin-dir DIR  --unit-dir DIR  (the last two are for tests; defaults are production)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR=/usr/local/sbin
UNIT_DIR=/etc/systemd/system
DRY=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --bin-dir) BIN_DIR="$2"; shift 2 ;;
    --unit-dir) UNIT_DIR="$2"; shift 2 ;;
    -h | --help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

run() {
  if [ "$DRY" -eq 1 ]; then echo "PLAN $*"; else echo "DO   $*"; "$@"; fi
}
die() { echo "setup-proxy-net: $*" >&2; exit 3; }

if [ "$DRY" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
  echo "setup-proxy-net: needs root (sudo), or use --dry-run" >&2
  exit 2
fi
docker info >/dev/null 2>&1 || die "Docker is not running (docker info failed)"

ip2int() {
  local IFS=. a b c d
  read -r a b c d <<<"$1"
  echo $(((a << 24) | (b << 16) | (c << 8) | d))
}

# overlaps CIDR1 CIDR2: true when the two networks share addresses.
overlaps() {
  local p1="${1#*/}" p2="${2#*/}" prefix mask
  prefix=$((p1 < p2 ? p1 : p2))
  mask=$((prefix == 0 ? 0 : (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF))
  [ $(($(ip2int "${1%/*}") & mask)) -eq $(($(ip2int "${2%/*}") & mask)) ]
}

# refuse_clashing_route SUBNET: a route of something other than a Docker bridge that overlaps SUBNET would
# be cut by Docker's bridge route (and could take SSH with it).
refuse_clashing_route() {
  local subnet="$1" route rest
  while read -r route rest; do
    case "$route" in
      default) continue ;;
      blackhole | unreachable | prohibit | throw) read -r route rest <<<"$rest" ;;
    esac
    [[ "$route" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(/[0-9]+)?$ ]] || continue
    case " $rest " in *" dev docker0 "* | *" dev br-"*) continue ;; esac
    case "$route" in */*) ;; *) route="$route/32" ;; esac
    if overlaps "$subnet" "$route"; then
      die "subnet $subnet would clash with the existing route $route; pick another subnet or remove the route"
    fi
  done < <(ip -4 route show)
}

# ensure_network NAME SUBNET
ensure_network() {
  local name="$1" subnet="$2" current
  if current="$(docker network inspect "$name" -f '{{(index .IPAM.Config 0).Subnet}}' 2>/dev/null)"; then
    [ "$current" = "$subnet" ] || die "network $name exists with subnet $current, expected $subnet"
    echo "OK   network $name ($subnet) exists"
    return
  fi
  refuse_clashing_route "$subnet"
  run docker network create --driver bridge --subnet "$subnet" "$name"
}

# install_file MODE SRC DEST: copy only when different; sets `changed`.
changed=0
install_file() {
  if ! cmp -s "$2" "$3" 2>/dev/null; then
    run install -m "$1" "$2" "$3"
    changed=1
  fi
}

refuse_clashing_route 10.232.0.0/24   # demo-net is created by the demo compose file, but must not clash either
ensure_network proxy-egress 10.231.0.0/24
ensure_network demo-egress 10.233.0.0/24
install_file 0755 "$HERE/pruefstand-firewall.sh" "$BIN_DIR/pruefstand-firewall.sh"
install_file 0644 "$HERE/pruefstand-firewall.service" "$UNIT_DIR/pruefstand-firewall.service"
[ "$changed" -eq 0 ] || run systemctl daemon-reload
run systemctl enable pruefstand-firewall
run systemctl restart pruefstand-firewall
