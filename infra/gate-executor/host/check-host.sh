#!/usr/bin/env bash
# check-host.sh (T6.2a S9, D1090): read-only checks of the executor VM, run as user pruefstand.
# Prints CSV rows `check,OK|FAIL,detail`; exit 0 when every row is OK, 1 otherwise. Changes nothing.
# Env: OWNER_USER (the owner login, the only other member of group docker), PRUEFSTAND_DATA_ROOT
#      (default /mnt/pruefstand), CLUSTER_SSH_HOST (default cairo-s101lp), LOCK_DIR (default /var/lib/pruefstand),
#      MIN_FREE_GB (default 20).
set -uo pipefail

fails=0
row() { echo "$1,$2,${3//,/;}"; [ "$2" = OK ] || fails=$((fails + 1)); }
check() { local name="$1" detail="$2"; shift 2; if "$@" >/dev/null 2>&1; then row "$name" OK "$detail"; else row "$name" FAIL "$detail"; fi; }

lock_dir="${LOCK_DIR:-/var/lib/pruefstand}"
data_root="${PRUEFSTAND_DATA_ROOT:-/mnt/pruefstand}"
min_gb="${MIN_FREE_GB:-20}"
owner="${OWNER_USER:-}"

user_is_pruefstand() { [ "$(id -un)" = pruefstand ]; }
in_docker_group() { id -nG | tr ' ' '\n' | grep -qx docker; }
docker_members_exact() {
  [ -n "$owner" ] || return 1
  local members
  members="$(getent group docker | cut -d: -f4 | tr ',' '\n' | sort | paste -sd, -)"
  [ "$members" = "$(printf '%s\n' pruefstand "$owner" | sort | paste -sd, -)" ]
}
lock_ok() {
  local f="$lock_dir/gpu.lock"
  [ -w "$f" ] && [ "$(stat -c '%a %G' "$f")" = "660 pruefstand" ]
}
units_active() { systemctl is-active --quiet pruefstand-tunnel pruefstand-runner; }
tunnel_answers() { curl -fsS -m 5 http://127.0.0.1:11434/api/tags; }
data_root_ok() {
  [ -d "$data_root" ] && [ -w "$data_root" ] || return 1
  local free_kb
  free_kb="$(df -Pk "$data_root" | awk 'NR == 2 {print $4}')"
  [ "${free_kb:-0}" -ge $((min_gb * 1024 * 1024)) ]
}
cluster_ssh() {
  ssh -o BatchMode=yes -o ConnectTimeout=10 -i /home/pruefstand/.ssh/id_ed25519_cluster \
    "${CLUSTER_SSH_HOST:-cairo-s101lp}" true
}
docker0_gateway() { ip -4 addr show docker0 | grep -q 'inet 172\.17\.0\.1/'; }
proxy_egress() {
  [ "$(docker network inspect proxy-egress --format '{{(index .IPAM.Config 0).Subnet}}')" = 10.231.0.0/24 ]
}
tunnel_binds_only_expected() {
  local addrs
  addrs="$(ss -ltnH 'sport = :11434' | awk '{print $4}' | sed 's/:11434$//' | sort -u | paste -sd, -)"
  [ "$addrs" = "127.0.0.1,172.17.0.1" ]
}

check user pruefstand user_is_pruefstand
check docker-group "pruefstand is in group docker" in_docker_group
check docker-members "group docker = pruefstand + ${owner:-<OWNER_USER unset>}" docker_members_exact
check gpu-lock "$lock_dir/gpu.lock writable; mode 660; group pruefstand" lock_ok
check units "pruefstand-tunnel and pruefstand-runner active" units_active
check tunnel "127.0.0.1:11434/api/tags answers" tunnel_answers
check data-root "$data_root writable; >= ${min_gb} GB free (ADR-0019)" data_root_ok
check cluster-ssh "BatchMode ssh to the cluster with the pruefstand key" cluster_ssh
check docker0 "172.17.0.1 on docker0" docker0_gateway
check proxy-egress "network proxy-egress has subnet 10.231.0.0/24" proxy_egress
check tunnel-binds "port 11434 listens on 127.0.0.1 and 172.17.0.1 only" tunnel_binds_only_expected

[ "$fails" -eq 0 ]
