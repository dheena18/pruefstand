"""Entrypoint of the Prüfstand GitHub Action: run, gate, report (T1.12 S1).

Reads the inputs GitHub passes as ``INPUT_*`` environment variables, calls the ``pruefstand`` CLI
with argument lists (never through a shell), writes ``status``, ``run-dir`` and ``comment-path`` to
``$GITHUB_OUTPUT``, appends the Markdown report to ``$GITHUB_STEP_SUMMARY`` and exits with the exit
code of ``pruefstand gate`` (0 pass or warn, 1 fail).
"""

import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

EXIT_USAGE = 2
EXIT_RUNTIME = 3
CLI = "pruefstand"
CLI_TIMEOUT_S = 3600
TIERS = ("pr", "nightly", "bench")
COMMENT_FILE = "comment.md"
GATE_FILE = "gate.json"

Invoker = Callable[[Sequence[str]], tuple[int, str]]
"""Runs the CLI with the given arguments and returns ``(exit code, stdout)``."""


class UsageError(Exception):
    """An input is missing or invalid (exit code 2)."""


@dataclass(frozen=True)
class ActionInputs:
    """The five inputs of ``action.yml``."""

    config: str
    tier: str
    baseline_run: str
    fail_on_warn: bool
    output_dir: str


def _say(message: str) -> None:
    sys.stderr.write(f"{message}\n")


def _input(env: Mapping[str, str], name: str, default: str) -> str:
    """Value of input ``name``; GitHub keeps the hyphen in the variable name, ``_`` also works."""
    upper = name.upper()
    for key in (f"INPUT_{upper}", f"INPUT_{upper.replace('-', '_')}"):
        value = env.get(key, "").strip()
        if value:
            return value
    return default


def read_inputs(env: Mapping[str, str]) -> ActionInputs:
    """Parse and validate the inputs.

    Args:
        env: The process environment.

    Returns:
        The validated inputs.

    Raises:
        UsageError: A required input is empty or a value is not allowed.
    """
    tier = _input(env, "tier", "pr")
    if tier not in TIERS:
        msg = f"tier must be one of {', '.join(TIERS)}, got '{tier}'"
        raise UsageError(msg)
    flag = _input(env, "fail-on-warn", "false").lower()
    if flag not in {"true", "false"}:
        msg = f"fail-on-warn must be true or false, got '{flag}'"
        raise UsageError(msg)
    baseline = _input(env, "baseline-run", "")
    if not baseline:
        msg = (
            "baseline-run is required: a run directory of the same config and dataset "
            "(--from-store comes with T6.1)"
        )
        raise UsageError(msg)
    return ActionInputs(
        config=_input(env, "config", "pruefstand.yaml"),
        tier=tier,
        baseline_run=baseline,
        fail_on_warn=flag == "true",
        output_dir=_input(env, "output-dir", ".pruefstand/out"),
    )


def run_cli(args: Sequence[str]) -> tuple[int, str]:
    """Run ``pruefstand <args>`` as a subprocess without a shell.

    Args:
        args: Arguments after the program name.

    Returns:
        The exit code and the captured stdout. Stderr goes straight to the step log.
    """
    try:
        done = subprocess.run(  # noqa: S603  (argument list, fixed program name, no shell)
            [CLI, *args],
            stdout=subprocess.PIPE,
            text=True,
            check=False,
            timeout=CLI_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        _say(f"error: pruefstand {args[0]} did not finish within {CLI_TIMEOUT_S} s")
        return EXIT_RUNTIME, ""
    return done.returncode, done.stdout


def _append(path_text: str | None, text: str) -> None:
    if not path_text:
        return
    with Path(path_text).open("a", encoding="utf-8") as handle:
        handle.write(text)


def _check_paths(inputs: ActionInputs) -> None:
    if not Path(inputs.config).is_file():
        msg = f"config file not found: {inputs.config}"
        raise UsageError(msg)
    if not Path(inputs.baseline_run).is_dir():
        msg = f"baseline-run is not a run directory: {inputs.baseline_run}"
        raise UsageError(msg)


def _gate_args(inputs: ActionInputs, run_dir: str) -> list[str]:
    args = ["gate", "--config", inputs.config, "--candidate", run_dir]
    args += ["--baseline", inputs.baseline_run]
    return [*args, "--fail-on-warn"] if inputs.fail_on_warn else args


def _status(run_dir: str) -> str:
    try:
        data = json.loads((Path(run_dir) / GATE_FILE).read_text(encoding="utf-8"))
        return str(data["status"])
    except (OSError, ValueError, KeyError):
        return "unknown"


def _pipeline(inputs: ActionInputs, env: Mapping[str, str], invoke: Invoker) -> int:
    """Run, gate and report; returns the exit code of ``gate``."""
    code, stdout = invoke(
        ["run", "--config", inputs.config, "--tier", inputs.tier, "--out", inputs.output_dir]
    )
    lines = stdout.strip().splitlines()
    if code != 0 or not lines:
        return code or EXIT_RUNTIME
    run_dir = lines[-1].strip()
    gate_code, _ = invoke(_gate_args(inputs, run_dir))
    if gate_code not in {0, 1}:
        return gate_code
    code, report = invoke(["report", "--run", run_dir, "--format", "md"])
    if code != 0:
        return code
    comment = Path(inputs.output_dir) / COMMENT_FILE
    comment.write_text(report, encoding="utf-8")
    _append(env.get("GITHUB_STEP_SUMMARY"), report)
    outputs = {"status": _status(run_dir), "run-dir": run_dir, "comment-path": str(comment)}
    _append(env.get("GITHUB_OUTPUT"), "".join(f"{k}={v}\n" for k, v in outputs.items()))
    return gate_code


def main(env: Mapping[str, str] | None = None, *, invoke: Invoker = run_cli) -> int:
    """Run the Action.

    Args:
        env: The environment to read inputs and output file names from; defaults to ``os.environ``.
        invoke: How the CLI is called; tests replace it to run the CLI in the test process.

    Returns:
        The gate exit code (0 pass or warn, 1 fail), 2 for invalid inputs, 3 for a runtime error.
    """
    if env is None:
        import os  # noqa: PLC0415  (only the real entry needs the process environment)

        env = os.environ
    try:
        inputs = read_inputs(env)
        _check_paths(inputs)
        Path(inputs.output_dir).mkdir(parents=True, exist_ok=True)
    except UsageError as exc:
        _say(f"error: {exc}")
        return EXIT_USAGE
    except OSError as exc:
        _say(f"error: cannot create the output directory: {type(exc).__name__}")
        return EXIT_RUNTIME
    return _pipeline(inputs, env, invoke)


if __name__ == "__main__":
    sys.exit(main())
