#!/usr/bin/env bash
# ACTIONS_RUNNER_HOOK_JOB_STARTED (T6.2a S9): clean leftovers of a killed job before this one starts.
set -euo pipefail
exec bash "$(dirname "$(readlink -f "$0")")/job_cleanup.sh"
