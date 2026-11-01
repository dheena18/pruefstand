r"""Structural ReDoS guard for the ``re:`` forbidden entries.

A pattern is rejected when an unbounded repeat contains another repeat (``(a+)+``, ``(\w+\s?)+``)
or an alternation (``(a|aa)+``): those backtrack exponentially on a hostile answer. Bounded repeats
(``{0,5}``), a lone ``.*`` / ``\w*`` and alternations outside a repeat are fine. Matching also runs
under a timeout (``normalise.REGEX_TIMEOUT_S``), which catches what this check cannot see
(polynomial blow-ups such as ``.*.*.*.*x``).
"""

import re
from typing import Any

_REPEATS = frozenset({"MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"})
_UNBOUNDED_FROM = 100  # a repeat whose upper bound exceeds this counts as unbounded


def assert_safe_pattern(source: str) -> None:
    r"""Raise ``ValueError`` when ``source`` is invalid or structurally ReDoS-prone.

    Args:
        source: Regular-expression source (already folded).

    Raises:
        ValueError: The source does not parse, or has a nested / ambiguous unbounded repeat.

    Examples:
        >>> assert_safe_pattern(r"\b47(\\s|-)(tage\\w*|tägig\\w*)")
        >>> assert_safe_pattern("(a+)+$")  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        ValueError: unsafe forbidden regex '(a+)+$': nested unbounded repeat ...
    """
    try:
        parsed = re._parser.parse(source, re.IGNORECASE)  # type: ignore[attr-defined]  # stdlib parse tree, no public API
    except re.error as exc:
        msg = f"invalid regular expression {source!r}: {exc}"
        raise ValueError(msg) from exc
    reason = _find_problem(parsed, inside_unbounded=False)
    if reason is not None:
        msg = f"unsafe forbidden regex {source!r}: {reason} (catastrophic backtracking)"
        raise ValueError(msg)


def _find_problem(items: Any, *, inside_unbounded: bool) -> str | None:  # noqa: ANN401  (sre parse tree)
    for op, argument in items:
        name = op.name
        if name in _REPEATS:
            _low, high, body = argument
            if inside_unbounded and high > 1:
                return "nested unbounded repeat"
            problem = _find_problem(
                body, inside_unbounded=inside_unbounded or high > _UNBOUNDED_FROM
            )
        elif name == "BRANCH":
            if inside_unbounded:
                return "alternation inside an unbounded repeat"
            problem = next(
                (p for alt in argument[1] if (p := _find_problem(alt, inside_unbounded=False))),
                None,
            )
        else:
            problem = next(
                (
                    p
                    for child in _children(argument)
                    if (p := _find_problem(child, inside_unbounded=inside_unbounded))
                ),
                None,
            )
        if problem is not None:
            return problem
    return None


def _children(argument: Any) -> list[Any]:  # noqa: ANN401  (sre parse tree)
    """Sub-patterns nested in an opcode argument (groups, lookarounds, conditionals)."""
    if type(argument).__name__ == "SubPattern":
        return [argument]
    if isinstance(argument, (tuple, list)):
        return [child for item in argument for child in _children(item)]
    return []
