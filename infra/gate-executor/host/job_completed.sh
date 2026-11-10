#!/usr/bin/env bash
# ACTIONS_RUNNER_HOOK_JOB_COMPLETED (T6.2a S9): clean the job's resources after it ends.
set -euo pipefail
exec bash "$(dirname "$(readlink -f "$0")")/job_cleanup.sh"
