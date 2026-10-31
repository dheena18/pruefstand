# Ruleset bypass log

Every merge that used the `main` ruleset bypass is recorded here (D106, `ci-cd.md` §5). The bypass list
holds only the role *Repository admin* (the owner), mode "pull requests only", and is used **only when
the private executor cannot post `pruefstand/gate`** (VM, runner, tunnel, NAS or cluster outage, including a gated PR left at `error` "executor unhealthy
during run" / "executor infra error: <summary>; re-dispatch to retry" after the automatic infra
retry, Y5.2, A12-M1, once a re-dispatch did not help). The bypass is done from the owner's browser; the VM's
`gh` token has no admin rights (N4.4), and the runbook §2 step 7 drill verifies that it cannot use the bypass
(`gh pr merge --admin` from the VM is refused). If that drill ever failed and the bypass list was emptied, the
same outage merge is done by temporarily disabling the ruleset in the browser, logged here the same way. Any
other reason is not a valid bypass: fix the cause or wait.

Rules:

1. Before merging, write the reason in the PR description ("Bypass: executor outage since <time>, see
   `executor-down` issue #N").
2. Add a row below in the same PR (or, if impossible, in the next PR, the same day).
3. After the executor is back, dispatch `nightly.yml` in `dheena18/pruefstand-gate` from the browser (or wait
   for the next nightly; a dispatched nightly passes the guard (`run=true`) but still stops at the next 06:00 Berlin
   deadline, so dispatch it before about 23:00) and record its result in the last
   column. A nightly FAIL caused by a bypassed
   PR is handled like any regression (revert or fix PR).
4. A bypass that changes a gate threshold also needs a `docs/decisions.md` line.

| Date (UTC) | PR | Head SHA | Reason | Outage evidence | Follow-up nightly (run id, result) |
| --- | --- | --- | --- | --- | --- |
| – | – | – | – | – | – |
