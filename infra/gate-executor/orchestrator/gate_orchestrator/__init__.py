"""Gate executor orchestrator (T6.2a): trusted job selection, state, window and status logic.

Runs on the VM as user ``pruefstand`` from the private executor checkout (synced from
``infra/gate-executor/`` at a reviewed tag). The modules here are pure (API responses, clocks and
paths are injected) so they are unit-tested without the runner, the GPU or GitHub.
"""
