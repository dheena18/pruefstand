#!/usr/bin/env bash
# Read-only: the last N lines of the Ollama server log, REDACTED on the cluster before they leave (T3.1e, D560-D562).
#
# usage: log-tail.sh [N]     N = 1..1000 (integer, default 200); writes nothing on the cluster, takes no lock.
# Purpose: the model load lines (parallel slots, KV cache size, offload) for kv_bytes_per_token / slot count / overhead.
# Pipeline (bounded memory): tail -n N | cut -b1-4000 | drop control characters | sed redaction | cut -b1-2000.
# Redaction rules, in this order:
#   %2F-style escapes are decoded first; OLLAMA_MODELS -> <models-dir>, the ollama binary of the serve process ->
#   <ollama-bin>, $HOME -> <home>, the login and the host name -> <cluster-user> / <host> (a name of 4+ characters
#   anywhere, even inside user_x or x2; a shorter one between non-alphanumerics), /home/<x> -> <home>, /data/<x> ->
#   <data-dir>, every IPv4 / IPv6 address, URL host, localhost, user@host, dotted host:port, "port N", "-p N" except
#   127.0.0.1:11434, GPU uuids, sha256 digests, secrets (Bearer/Basic values, key=value pairs whose key names a secret,
#   a token or key with a 12+ character value, well-known token prefixes, PEM and ssh keys, runs of 32+ token characters).
#   Kept: source file:line pairs, "std::", "BOS token = 11", "n_tokens = 512", absolute library paths, load numbers.
# Fail closed: the redacted text is held back, scanned once more (login, host, home, models dir, /data/ and /home/,
# IPv4, IPv6, URL hosts, user@host, GPU uuids, sha256 digests, 32+ character runs, secret-looking pairs) and only then printed.
# The scan is a safety net for what the rules above should have removed, not a second redaction. A failure of any step
# prints NOTHING on stdout and exits non-zero (the message names no log content).
# Exit: 0 ok, 1 log or cluster.env unusable, 5 redaction failed or a leak was found, 64 usage.
set -euo pipefail

BIN="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
. "$BIN/common.sh"

MAX_LINES=1000
LOOPBACK="127.0.0.1:11434"
usage="usage: log-tail.sh [N]   (N = 1..$MAX_LINES, default 200)"
if [ "$#" -gt 1 ]; then die "$usage" 64; fi
n="${1-200}"
n_re='^[1-9][0-9]{0,3}$'
if ! [[ $n =~ $n_re ]] || [ "$n" -gt "$MAX_LINES" ]; then die "$usage" 64; fi
load_cluster_env "$BIN/cluster.env"
if [ -z "${OLLAMA_LOG:-}" ] || ! [ -r "$OLLAMA_LOG" ]; then die "the Ollama log is not readable" 1; fi

LOGIN="$(id -un)"
HOST="${HOSTNAME:-}"
SRC_EXT='go|c|cc|cpp|cxx|cu|cuh|h|hpp|py|rs|m|mm|metal|js'
V6_PART='[0-9A-Fa-f]{1,4}(:[0-9A-Fa-f]{1,4})*'
V6_RE="(^|[^A-Za-z0-9_:.])(${V6_PART})?::(${V6_PART})?([^A-Za-z0-9_:.]|\$)"
SECRET_ANY='(secret|passw|credential|authorization|api[_-]?key|access[_-]?key|private[_-]?key|(auth|access|refresh|session)[_-]?token)'
SECRET_LONG='(token|key)'
VAL_LONG='["'"'"']?[A-Za-z0-9_.+/=~-]{12,}'

esc() { printf '%s' "$1" | sed 's/[][\.*^$/#|()+?{}]/\\&/g'; }

# a name pattern: 4+ characters anywhere, shorter ones only between non-alphanumerics (case-insensitive)
name_re() { # name -> ERE
  if [ "${#1}" -ge 4 ]; then esc "$1"; else printf '(^|[^A-Za-z0-9])%s([^A-Za-z0-9]|$)' "$(esc "$1")"; fi
}

SED_ARGS=()
add_path() { # literal path, replacement: only a path of two or more characters that is not "/"
  if [ "${#1}" -gt 1 ] && [ "$1" != "/" ]; then SED_ARGS+=(-e "s#$(esc "$1")#$2#g"); fi
}
add_name() { # literal name, replacement
  if [ -z "$1" ]; then return 0; fi
  if [ "${#1}" -ge 4 ]; then
    SED_ARGS+=(-e "s#$(name_re "$1")#$2#gI")
  else
    SED_ARGS+=(-e "s#$(name_re "$1")#\\1$2\\2#gI" -e "s#$(name_re "$1")#\\1$2\\2#gI")
  fi
}

build_rules() {
  local pid exe
  SED_ARGS+=(-e 's#%2[Ff]#/#g' -e 's#%2[Ee]#.#g' -e 's#%40#@#g' -e 's#%3[Aa]#:#g')
  add_path "$OLLAMA_MODELS" "<models-dir>"
  for pid in $(serve_pids); do
    exe="$(readlink -f "$PROC/$pid/exe" 2>/dev/null || true)"
    case "$exe" in /*) add_path "$exe" "<ollama-bin>" ;; esac
  done
  add_path "$HOME" "<home>"
  add_name "$LOGIN" "<cluster-user>"
  add_name "$HOST" "<host>"
  add_name "${HOST%%.*}" "<host>"
  local tok='[A-Za-z0-9_.+/=~-]'
  SED_ARGS+=(
    -e 's#sha256[-:][0-9A-Fa-f]{64}#sha256-<digest>#g'
    -e 's#GPU-[0-9A-Fa-f-]{8,}#GPU-<uuid>#g'
    -e 's#/home/[^/[:space:]"'"'"']+#<home>#g'
    -e 's#/Users/[^/[:space:]"'"'"']+#<home>#g'
    -e 's#/data/[^/[:space:]"'"'"']+#<data-dir>#g'
    -e 's#-----BEGIN[^-]*-----#<redacted-key>#g'
    -e "s#((Bearer|Basic)[[:space:]]+)${tok}+#\\1<redacted>#gI"
    -e "s#(Token[[:space:]]+)${tok}{16,}#\\1<redacted>#g"
    -e "s#([A-Za-z0-9_.-]*${SECRET_ANY}[A-Za-z0-9_.-]*[\"']?[[:space:]]*[=:][[:space:]]*)[^[:space:],;]+#\\1<redacted>#gI"
    -e "s#([A-Za-z0-9_.-]*${SECRET_LONG}[\"']?[[:space:]]*[=:][[:space:]]*)${VAL_LONG}#\\1<redacted>#gI"
    -e 's#(gh[pousr]_|github_pat_|sk-|hf_|xox[abprs]-|AKIA|AIza)[A-Za-z0-9_-]{12,}#<redacted>#g'
    -e 's#eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_.-]+#<redacted>#g'
    -e 's#ssh-(rsa|ed25519|dss)[[:space:]]+[A-Za-z0-9+/=]+#<redacted-key>#g'
    -e 's#[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+#<user>@<host>#g'
    -e "s#(^|[^0-9.])127\\.0\\.0\\.1:11434([^0-9]|\$)#\\1@@LOOPBACK@@\\2#g"
    -e "s#(^|[^0-9.])127\\.0\\.0\\.1:11434([^0-9]|\$)#\\1@@LOOPBACK@@\\2#g"
    -e 's#[0-9]{1,3}(\.[0-9]{1,3}){3}(:[0-9]+)?#<ip>#g'
    -e 's#\[[0-9A-Fa-f.]*:[0-9A-Fa-f:.]*\](:[0-9]+)?#<ip>#g'
    -e 's#([0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}#<ip>#g'
    -e "s#${V6_RE}#\\1<ip>\\6#g"
    -e "s#${V6_RE}#\\1<ip>\\6#g"
    -e 's#(https?://)[^/[:space:]"'"'"'@:?]+#\1<host>#g'
    -e 's#@@LOOPBACK@@#@@LB@@#g'
    -e 's#(^|[^A-Za-z0-9_.-])localhost(:[0-9]+)?#\1<host>#gI'
    -e "s#\\.(${SRC_EXT}):([0-9])#.\\1@@SRC@@\\2#g"
    -e 's#([A-Za-z0-9-]+\.)+[A-Za-z0-9-]+:[0-9]{2,5}([^A-Za-z0-9]|$)#<host>\2#g'
    -e "s#\\.(${SRC_EXT})@@SRC@@#.\\1:#g"
    -e 's#((^|[^A-Za-z])port["'"'"']?[=: ]+)["'"'"']?[0-9]+#\1<port>#gI'
    -e 's#((^|[[:space:]])-p[[:space:]]*)[0-9]+#\1<port>#g'
    -e 's#<(host|ip)>:[0-9]+#<\1>#g'
    -e 's#[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.(local|lan|internal|intranet|corp|home|localdomain|net|com|org|edu|de|io|ai|co|dev|info|uk|eu|fr|ch|at|ac\.[a-z]{2})([^A-Za-z0-9]|$)#<host>\3#g'
    -e 's#[A-Za-z0-9+=]{32,}#<redacted>#g'
    -e 's#(^|[^A-Za-z0-9+/_=.-])[A-Za-z0-9+=][A-Za-z0-9+/_=-]{31,}#\1<redacted>#g'
    -e 's#@@LB@@#127.0.0.1:11434#g'
  )
}

# What must not be in the redacted text. Returns 0 when something leaked.
leaks() { # redacted text on stdin
  local text allowed_free
  text="$(cat)"
  allowed_free="${text//$LOOPBACK/}"
  if [ -n "$OLLAMA_MODELS" ] && [[ $text == *"$OLLAMA_MODELS"* ]]; then return 0; fi
  if [ "${#HOME}" -gt 1 ] && [[ $text == *"$HOME"* ]]; then return 0; fi
  if [[ $text == *"/data/"* ]] || [[ $text == *"/home/"* ]]; then return 0; fi
  if grep -qiE "$(name_re "$LOGIN")" <<<"$text"; then return 0; fi
  if [ -n "$HOST" ] && grep -qiE "$(name_re "$HOST")" <<<"$text"; then return 0; fi
  if grep -qE '[0-9]{1,3}(\.[0-9]{1,3}){3}' <<<"$allowed_free"; then return 0; fi
  if grep -qE "$V6_RE" <<<"$text"; then return 0; fi
  if grep -qiE 'https?://[^</[:space:]"]' <<<"$allowed_free"; then return 0; fi
  if grep -qE '[A-Za-z0-9._%+-]+@[A-Za-z0-9]' <<<"$text"; then return 0; fi
  if grep -qE 'GPU-[0-9A-Fa-f]|sha256[-:][0-9A-Fa-f]{16}' <<<"$text"; then return 0; fi
  if grep -qE '[A-Za-z0-9+=]{32,}' <<<"$text"; then return 0; fi
  if grep -qiE '(Bearer|Basic)[[:space:]]+[^<[:space:]]' <<<"$text"; then return 0; fi
  if grep -qiE "${SECRET_ANY}[A-Za-z0-9_.-]*[\"']?[[:space:]]*[=:][[:space:]]*[^<[:space:]]" <<<"$text"; then
    return 0
  fi
  if grep -qiE "${SECRET_LONG}[\"']?[[:space:]]*[=:][[:space:]]*${VAL_LONG}" <<<"$text"; then return 0; fi
  return 1
}

main() {
  local redacted
  build_rules || return 5
  redacted="$(LC_ALL=C tail -n "$n" "$OLLAMA_LOG" | LC_ALL=C cut -b1-4000 | LC_ALL=C tr -d '\000-\010\013-\037\177' |
    LC_ALL=C sed -E "${SED_ARGS[@]}" | LC_ALL=C cut -b1-2000)" || return 5
  if leaks <<<"$redacted"; then return 5; fi
  printf '%s\n' "$redacted"
}

if ! out="$(main)"; then
  die "redaction failed or would leak; nothing printed" 5
fi
printf '%s\n' "$out"
