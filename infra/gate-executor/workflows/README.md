# Private executor workflows (source)

The `*.yml` files of this directory run in the **private** repo `dheena18/pruefstand-gate`, not here:
`scripts/sync_executor.sh` copies them into its `.github/workflows/` (only `*.yml`; this README stays here).
They are written by T6.2b (`gate-executor.yml` with `workflow_dispatch` only, `baseline-promote.yml`,
`nightly.yml`, `backup.yml`; `docs/engineering/ci-cd.md` §1.2) and checked by `scripts/check_workflows.py`.
