# Private executor workflows (source)

The `*.yml` files of this directory run in the **private** repo `dheena18/pruefstand-gate`, not here:
`scripts/sync_executor.sh` copies them into its `.github/workflows/` (only `*.yml`; this README stays here).
They are written by T6.2b (`gate-executor.yml` with `workflow_dispatch` only, `baseline-promote.yml`,
`nightly.yml`, `backup.yml`; `docs/engineering/ci-cd.md` §1.2) and checked by `scripts/check_workflows.py`.

Checked by `scripts/workflow_private.py` (the private rules of the T6.2b test table,
`scripts/tests/test_check_workflows_private.py`, D1093), not by the public guard. The `run:` steps on the A40
runner call the `gate-orchestrator` command (subcommands `dispatch`, `promote-poll`, `nightly`, `backup-check`);
the hosted `guard` job of `nightly.yml` calls `python3 -m gate_orchestrator night-guard`. That CLI is the T6.2a
slice "orchestrator CLI" (D1095); it must be merged and installed on the runner before an `executor-*` tag that
carries these files is synced.
