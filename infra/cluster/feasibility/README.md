# Cluster feasibility probe (T0.6)

Evidence for the go / no-go on serving all tier-2 models with one Ollama server on `cairo-s101lp`
(ADR-0018, ADR-0019). The verdict is judged by the owner; `summarise.py` only reports it.

**Never run any of this during a gate job, a nightly or a baseline promote.** `probe.sh` is read-only
except its opt-in cold-load step; `tunnel_check.sh` sends real generation requests and therefore needs
the GPU lock and refuses without `PRUEFSTAND_LOCK_HELD=1`.

| Step | Machine / user | Command | Notes |
| --- | --- | --- | --- |
| 1 Probe (read-only) | VM, user `pruefstand` (holds the cluster key) | `sudo -u pruefstand ssh cairo-s101lp 'bash -s' < infra/cluster/feasibility/probe.sh > probe.out` | piped, nothing is copied or written on the cluster; `model-load` prints `SKIP`; the Ollama binary comes from the process serving :11434; every output line is filtered (binary path, install prefix, home, login scrubbed; a line that still leaks becomes `CHECK redact FAIL leak suppressed`), stderr goes through the same filter; still check `probe.out` by eye before committing |
| 2 Cold load (optional, C6) | VM, owner user, then `pruefstand` | `touch /var/lib/pruefstand/MAINTENANCE`; unload the loaded model by hand (`keep_alive: 0`); `pruefstand-lock sudo -n -u pruefstand ssh cairo-s101lp 'MEASURE_LOAD=1 bash -s' < infra/cluster/feasibility/probe.sh`; `rm /var/lib/pruefstand/MAINTENANCE` | loads the 27B generator (keep_alive 5m); measured only if `/api/ps` lists no model; FAIL on a non-2xx answer, an `error` field, a curl failure or timeout, or when `/api/ps` does not list the model; once the request is sent the model is unloaded again (keep_alive 0, status and `/api/ps` checked, else the line says "unload by hand"; if the probe is killed in between, keep_alive 5m bounds it); under the lock and `MAINTENANCE` |
| 3 API checks | VM, owner user, wrapped | `pruefstand-lock sudo -n -u pruefstand --preserve-env=PRUEFSTAND_LOCK_HELD bash infra/cluster/feasibility/tunnel_check.sh --use-existing-tunnel > tunnel.out` | real chat, embedding and SSH calls; the sudoers line for this form is not final until T0.7 is merged, adapt it to the final wrapper |
| 4 Save | VM, owner user | `cat probe.out tunnel.out > infra/cluster/feasibility/probe-<date>.out` | no host, port, ngrok URL or secret in the file |
| 5 Verdict | any | `uv run python infra/cluster/feasibility/summarise.py < infra/cluster/feasibility/probe-<date>.out` | last line `VERDICT: ...`; then fill `gpu-cluster.md` §0.2 C1-C8 and the Decision line |

`sudo -u pruefstand ssh cairo-s101lp` in steps 1-2 is a T0.6 exception to the rule that the owner reaches the
cluster only through the `pruefstand-cluster` wrapper (that wrapper arrives with T3.1a); do not copy the pattern.

Quota probe (C9, `scripts/models/quota_probe.py`): see `docs/engineering/ci-cd.md` §1.1a. The candidate model
ids in `DEFAULT_MODELS` are **unverified** against the GitHub Models catalogue; pass `--models` to override.
After the first real run, commit the raw `quota-burst.jsonl` as a fixture for the parser tests (follow-up).
