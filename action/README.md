# Prüfstand GitHub Action

Runs `pruefstand run`, `pruefstand gate` and `pruefstand report --format md` in one container and exits with the
gate's exit code. Linux runners only. T1.12; the published form (`dheena18/pruefstand-action`) arrives with T9.1b.

## Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `config` | `pruefstand.yaml` | Config file, relative to the workspace. |
| `tier` | `pr` | `pr`, `nightly` or `bench`. |
| `baseline-run` | _(none)_ | **Required until T6.1** adds `--from-store`: a run directory of the same config and dataset (same `eval_fingerprint`). Empty exits with code 2. |
| `fail-on-warn` | `false` | `true` makes a WARN result exit 1 as well. |
| `output-dir` | `.pruefstand/out` | Where the run directory and `comment.md` are written. Keep the baseline run in the same directory so the report can name it. |

## Outputs

`status` (`pass`, `warn`, `fail`, `insufficient_data`), `run-dir` (candidate run directory with `run.json` and
`gate.json`), `comment-path` (Markdown report, the PR comment body). The report is also appended to the job
summary. Exit code: 0 pass or warn, 1 fail (or warn with `fail-on-warn`), 2 invalid input or config, 3 runtime
error (target unreachable, run stopped early).

## Permissions and forks

The Action needs no token and no secret: it reads the workspace and talks to your target. Give the job
`contents: read` only. Posting the comment is a separate job with `pull-requests: write` that runs none of your
code (`examples/workflows/pruefstand.yml`). Pull requests from forks get a read-only token: skip the comment job
there; the report is in the job summary. Judged metrics use GitHub Models only in this repository's own
`live-e2e.yml`; the Action runs deterministic metrics unless you configure a judge yourself.

## Target as a service container

Run the system under test as a `services:` container of the job and point `target.url` in `pruefstand.yaml` at
`http://localhost:<port>`. The Action container uses the host network of the runner in this repository's
selftest (`docker run --network host`); with `uses:` the runner's own container networking applies, so publish
the service port on the runner (`ports: [8000:8000]`).

## `uses:` path and the container user

Until T9.1b publishes the image, the path is `dheena18/pruefstand/action@<commit sha>`. Two things to know:

* `action/Dockerfile` needs the **repository root** as build context (it installs the `pruefstand` package from
  the workspace). GitHub builds a `uses: ./action` step with `action/` as context, so that form does not work
  yet; `action-selftest.yml` builds the image from the root and runs it with `docker run`. T9.1b switches
  `action.yml` to the published image.
* The image runs as uid 10001 (CLAUDE.md section 8). The workspace is owned by the runner user, so a container
  that must write `output-dir` needs `--user "$(id -u):$(id -g)"` (the selftest does). T9.1b decides how the
  published Action handles this.

## Comment check

`action/check_comment.py` is the only code the `comment` job of `live-e2e.yml` runs, checked out from the **base**
SHA: the first line must be `<!-- pruefstand:pr-comment -->` and the body at most 60 000 characters.
