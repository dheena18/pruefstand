"""Expression taint of the workflow guard (review F3, D1121): what may reach a shell or a script.

A value is *tainted* when an expression in it reads an attacker-influenced value: a
``github.event.*`` path outside ``EVENT_VALUES``, the whole ``github`` context, a computed index,
an untrusted context (``UNTRUSTED``), a step or job output, an action / ``workflow_call`` input,
or an ``env.*`` / ``matrix.*`` name that is itself tainted (computed to a fixed point over the
workflow, job and step ``env`` and over ``strategy.matrix`` incl. ``include`` / ``exclude``).
Code fields (``run``, ``shell``, ``working-directory``, ``with.script``) may interpolate no
tainted expression and no step or job output; other ``with:`` inputs no event, untrusted or
tainted env/matrix value. A ``run`` that writes ``$GITHUB_ENV`` / ``$GITHUB_PATH`` anywhere may
contain no ``${{ }}`` at all, no tainted env variable and no runner variable an attacker sets.
This is defence in depth, not a proof (known limits: D1121).
"""

import re
from dataclasses import dataclass, field

from workflow_model import Doc, strings
from workflow_policy import BRACKET_NAME, EVENT_VALUES, EXPRESSION, UNTRUSTED

_EVENT_PATH = re.compile(r"github\.event(?![\w-])((?:\.[\w*-]+|\[\s*[\w*]+\s*\])*)")
_BARE_GITHUB = re.compile(r"(?<![\w.])github(?![\w.\[-])")
_COMPUTED = re.compile(r"\[(?!\s*(?:\d+|\*)\s*\])")
_LITERAL = re.compile(r"'(?:[^']|'')*'")
_CONTEXT_REF = re.compile(r"\b(env|matrix)\.([\w-]+)")
_OUTPUT_REF = re.compile(r"\b(?:steps|needs)\.[\w-]+\.outputs\b|\bneeds\.\*|\bjob\.outputs\b")
_INPUT_REF = re.compile(r"\binputs\.")
_ENV_FILE = re.compile(r"GITHUB_ENV|GITHUB_PATH|\$\{\{\s*github\s*\.\s*(?:env|path)\b", re.I)
_SHELL_VAR = re.compile(r"\$\{?([A-Za-z_]\w*)")
_RUNNER_UNTRUSTED = frozenset(
    {"GITHUB_HEAD_REF", "GITHUB_BASE_REF", "GITHUB_REF_NAME", "GITHUB_REF", "GITHUB_EVENT_PATH"}
)
CODE_KEYS = ("run", "shell", "working-directory")


@dataclass
class Context:
    """Taint known for one job: tainted env names, matrix names, and whether inputs are."""

    env: dict[str, object] = field(default_factory=dict)
    matrix: set[str] = field(default_factory=set)
    inputs: bool = False


def normalised(code: str) -> list[str]:
    """The ``${{ }}`` expressions of ``code``: quoted names to dots, lower case."""
    return [BRACKET_NAME.sub(r".\1", e).lower() for e in EXPRESSION.findall(code)]


def event_findings(expression: str) -> list[str]:
    """Event paths outside the allow-list, the bare ``github`` context, computed indexes."""
    bad = []
    bare = _LITERAL.sub("''", expression)
    for match in _EVENT_PATH.finditer(bare):
        path = "github.event" + re.sub(r"\s+", "", match.group(1))
        if EVENT_VALUES.fullmatch(path) is None:
            bad.append(path)
    if _BARE_GITHUB.search(bare):
        bad.append("github")  # the whole context, e.g. toJSON(github)
    if _COMPUTED.search(bare):
        bad.append("a computed context index")
    return bad


def _source(expression: str, ctx: Context, tainted_env: set[str]) -> bool:
    if event_findings(expression) or UNTRUSTED.search(expression):
        return True
    if _OUTPUT_REF.search(expression) or (ctx.inputs and _INPUT_REF.search(expression)):
        return True
    return any(
        name in tainted_env if kind == "env" else (name in ctx.matrix or "*" in ctx.matrix)
        for kind, name in _CONTEXT_REF.findall(expression)
    )


def tainted_names(values: dict[str, object], ctx: Context) -> set[str]:
    """Names (lower case) of ``values`` that are tainted, to a fixed point (``env.A`` -> B)."""
    tainted: set[str] = set()
    while True:
        more = {
            k.lower()
            for k, v in values.items()
            if any(_source(e, ctx, tainted) for s in strings(v) for e in normalised(s))
        }
        if more <= tainted:
            return tainted
        tainted |= more


def matrix_taint(matrix: object, ctx: Context) -> set[str]:
    """Tainted matrix names; ``include`` / ``exclude`` entries count by their keys; ``*`` = all."""
    if isinstance(matrix, str):
        return {"*"} if tainted_names({"m": matrix}, ctx) else set()
    if not isinstance(matrix, dict):
        return set()
    flat: dict[str, object] = {}
    for key, value in matrix.items():
        if key in ("include", "exclude") and isinstance(value, str):
            flat[f"*#{len(flat)}"] = value  # a dynamic include/exclude can add any key
        elif key in ("include", "exclude") and isinstance(value, list):
            for entry in value:
                for name, item in entry.items() if isinstance(entry, dict) else ():
                    flat[f"{name}#{len(flat)}"] = item
        else:
            flat[str(key)] = value
    return {name.split("#")[0] for name in tainted_names(flat, ctx)}


@dataclass
class _Step:
    where: str
    step: Doc
    ctx: Context
    env: set[str]
    out: list[str] = field(default_factory=list)

    def add(self, message: str) -> None:
        self.out.append(f"{self.where}: {message}")


def _code(s: _Step, code: str, label: str) -> None:
    for expression in normalised(code):
        for path in event_findings(expression):
            s.add(f"{path} interpolated in run/with is not on the allow-list (injection)")
        for kind, name in _CONTEXT_REF.findall(expression):
            if name in (s.env if kind == "env" else s.ctx.matrix) or (
                kind == "matrix" and "*" in s.ctx.matrix
            ):
                s.add(f"{kind}.{name} carries an untrusted value into run/with (injection)")
        if label != "with" and (match := _OUTPUT_REF.search(expression)):
            s.add(f"{match.group(0)} interpolated in {label} (injection; pass it through env:)")
        if label != "with" and s.ctx.inputs and _INPUT_REF.search(expression):
            s.add(f"an action input is interpolated in {label} (pass it through env:)")
        if UNTRUSTED.search(expression):  # every label: run, script, shell, working-directory, with
            s.add("untrusted value interpolated in run/with input (injection)")


def _env_file(s: _Step, run: str) -> None:
    if not _ENV_FILE.search(run):
        return
    names = set(_SHELL_VAR.findall(run))
    bad = "${{" in run or bool(names & _RUNNER_UNTRUSTED)
    if bad or any(n.lower() in s.env for n in names):
        s.add(
            "GITHUB_ENV/GITHUB_PATH is written in a run block with an expression, a tainted env"
            " var or an attacker-set runner variable"
        )


def step_findings(
    where: str, step: Doc, ctx: Context, *, env_file_allowed: bool = False
) -> list[str]:
    """Findings of one step (or a job's own ``with:``) against the job's taint ``ctx``.

    ``env_file_allowed``: the step is on ``ENV_FILE_STEPS`` (its env-file block was reviewed).
    """
    env_values = {**ctx.env, **_mapping(step.get("env"))}
    s = _Step(where, step, ctx, tainted_names(env_values, ctx))
    for key in CODE_KEYS:
        value = step.get(key)
        if isinstance(value, str):
            _code(s, value, key)
    with_ = _mapping(step.get("with"))
    for key, value in with_.items():
        for text in strings(value):
            _code(s, text, "script" if key == "script" else "with")
    run = step.get("run")
    if isinstance(run, str) and not env_file_allowed:
        _env_file(s, run)
    return s.out


def _mapping(node: object) -> dict[str, object]:
    return {str(k): v for k, v in node.items()} if isinstance(node, dict) else {}


def mapping(node: object) -> dict[str, object]:
    """``node`` as a str-keyed dict, empty when it is not a mapping."""
    return _mapping(node)
