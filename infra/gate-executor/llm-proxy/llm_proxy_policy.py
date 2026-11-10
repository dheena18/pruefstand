"""Request policy of ``llm-proxy`` (T6.2a S4b; interfaces 1.5; D206, D242, D252, ADR-0018).

Pure functions, no I/O: :func:`build_policy` turns catalogue entries (``infra/gpu/models.yaml``)
into the per-tag policy of one run, :func:`decide` maps one candidate request to a
:class:`Forward` (the rewritten request) or a :class:`Reject` (403 + reason, nothing
forwarded), and :func:`is_reload` reads Ollama's ``load_duration`` from a forwarded response.

Rules (the single definition is interfaces 1.5):

* only ``POST /api/chat`` (generator tags), ``POST /api/embed`` (embed tags), ``GET /api/tags``;
* a bearer key compared in constant time; an empty configured key rejects everything;
* the body's ``model`` must be one of the run's tags (judges are never in the policy, ADR-0018);
* ``/api/chat`` always gets ``think: false`` (D1076, CLAUDE.md §5);
* ``num_ctx`` is always the catalogue value; ``keep_alive`` and every other load-time or unknown
  option key are dropped; ``temperature``, ``top_p`` and ``num_predict`` pass through inside the
  catalogue ``option_bounds`` (else 403 ``option out of bounds: <key>``); ``seed`` passes when it is
  an integer; a missing key gets the catalogue default; a key without bounds keeps the default.
"""

import hmac
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from llm_proxy_json import StrictJSONError, dump, load_object

CHAT, EMBED, TAGS = "/api/chat", "/api/embed", "/api/tags"
ROUTES: dict[tuple[str, str], str] = {
    ("POST", CHAT): "generator",
    ("POST", EMBED): "embed",
    ("GET", TAGS): "",
}
FORWARD_ROLES = frozenset({"generator", "embed"})
BOUNDED = ("temperature", "top_p", "num_predict")
RELOAD_NS = 1_000_000_000  # load_duration > 1 s = a model (re)load (SPEC 6.2)
Number = int | float


class PolicyError(ValueError):
    """A catalogue entry cannot become a proxy policy (judge, missing ``num_ctx``, bad bounds)."""


@dataclass(frozen=True)
class ModelPolicy:
    """What the proxy enforces for one tag: its role, ``num_ctx``, defaults and bounds."""

    role: str
    num_ctx: int
    defaults: Mapping[str, Number] = field(default_factory=dict)
    bounds: Mapping[str, tuple[Number, Number]] = field(default_factory=dict)


@dataclass(frozen=True)
class Forward:
    """Forward ``method path`` with ``body`` (``None`` for ``GET``) to the upstream."""

    method: str
    path: str
    body: bytes | None


@dataclass(frozen=True)
class Answer:
    """Answer locally with ``status`` and ``body``; nothing is forwarded (``GET /api/tags``)."""

    status: int
    body: bytes


@dataclass(frozen=True)
class Reject:
    """Answer ``status`` with ``{"error": reason}``; nothing is forwarded."""

    status: int
    reason: str


def _number_map(raw: object, where: str) -> dict[str, Number]:
    if not isinstance(raw, Mapping):
        msg = f"{where} must be a mapping"
        raise PolicyError(msg)
    out: dict[str, Number] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            msg = f"{where}.{key} must be a number"
            raise PolicyError(msg)
        out[str(key)] = value
    return out


def _bounds(raw: object, tag: str) -> dict[str, tuple[Number, Number]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        msg = f"option_bounds of {tag} must be a mapping"
        raise PolicyError(msg)
    out: dict[str, tuple[Number, Number]] = {}
    for key, pair in raw.items():
        values = list(pair) if isinstance(pair, list | tuple) else []
        numeric = all(isinstance(v, int | float) and not isinstance(v, bool) for v in values)
        if len(values) != 2 or not numeric or values[0] > values[1]:
            msg = f"option_bounds.{key} of {tag} must be [low, high]"
            raise PolicyError(msg)
        out[str(key)] = (values[0], values[1])
    return out


def build_policy(
    entries: Iterable[Mapping[str, object]], tags: Iterable[str]
) -> dict[str, ModelPolicy]:
    """The per-tag policy for one run.

    Args:
        entries: catalogue ``models`` entries (``tag``, ``role``, ``options``, ``option_bounds``).
        tags: the run's generator + embedding tags (bare Ollama tags, D221).

    Returns:
        ``{tag: ModelPolicy}`` for exactly ``tags``.

    Raises:
        PolicyError: a tag is not in the catalogue, is not a generator or embedding model (a judge,
            ADR-0018), or its ``options`` lack an integer ``num_ctx``.
    """
    by_tag = {str(e.get("tag")): e for e in entries}
    policy: dict[str, ModelPolicy] = {}
    for tag in tags:
        entry = by_tag.get(tag)
        if entry is None:
            msg = f"tag {tag} is not in the catalogue"
            raise PolicyError(msg)
        role = str(entry.get("role"))
        if role not in FORWARD_ROLES:
            msg = f"tag {tag} has role {role}; only generator and embed tags are allowed"
            raise PolicyError(msg)
        options = _number_map(entry.get("options", {}), f"options of {tag}")
        num_ctx = options.pop("num_ctx", None)
        if not isinstance(num_ctx, int):
            msg = f"options of {tag} need an integer num_ctx"
            raise PolicyError(msg)
        defaults = {k: v for k, v in options.items() if k in (*BOUNDED, "seed")}
        policy[tag] = ModelPolicy(role, num_ctx, defaults, _bounds(entry.get("option_bounds"), tag))
    return policy


def authorised(header: str | None, key: str) -> bool:
    """True when ``header`` is exactly ``Bearer <key>`` (constant time); empty keys never match."""
    if not key or header is None:
        return False
    return hmac.compare_digest(header.encode(), f"Bearer {key}".encode())


def _options(raw: object, model: ModelPolicy) -> dict[str, Number] | Reject:
    client = raw if isinstance(raw, Mapping) else {}
    out: dict[str, Number] = {"num_ctx": model.num_ctx}
    for key in (*BOUNDED, "seed"):
        value = client.get(key)
        if value is None or (key not in model.bounds and key != "seed"):
            if key in model.defaults:
                out[key] = model.defaults[key]
            continue
        bad_type = isinstance(value, bool) or not isinstance(value, int | float)
        if key == "seed":
            bad_type = bad_type or not isinstance(value, int)
        if bad_type or (key in model.bounds and not _inside(value, model.bounds[key])):
            return Reject(403, f"option out of bounds: {key}")
        out[key] = value
    return out


def _inside(value: Number, bound: tuple[Number, Number]) -> bool:
    return bound[0] <= value <= bound[1]


def decide(  # noqa: PLR0911 - one return per rejection reason keeps the rule table readable
    method: str,
    path: str,
    *,
    auth: str | None,
    body: bytes,
    key: str,
    policy: Mapping[str, ModelPolicy],
) -> Forward | Reject | Answer:
    """Map one candidate request to the request to forward, a local answer, or a 403.

    Args:
        method: HTTP method.
        path: request path including any query string (a query is rejected).
        auth: the ``Authorization`` header or ``None``.
        body: the raw request body (already size-capped by the server).
        key: the configured ``PRUEFSTAND_CANDIDATE_API_KEY``.
        policy: the run's :func:`build_policy` result.

    Returns:
        :class:`Forward` with the rewritten body, :class:`Answer` (the synthesised tag list of
        the run, never the upstream list, D1071) or :class:`Reject`.
    """
    role = ROUTES.get((method, path))
    if role is None:
        return Reject(403, f"path not allowed: {method} {path}")
    if not authorised(auth, key):
        return Reject(403, "missing or wrong bearer key")
    if method == "GET":
        return tags_answer(policy)
    try:
        data = load_object(body, role)
    except StrictJSONError as err:
        return Reject(403, str(err))
    model = policy.get(str(data.get("model")))
    if model is None or model.role != role:
        return Reject(403, "model not allowed")
    options = _options(data.get("options"), model)
    if isinstance(options, Reject):
        return options
    data.pop("keep_alive", None)
    data["options"] = options
    if role == "generator":
        data["think"] = False  # D1076: thinking always off, whatever the candidate sends
    try:
        return Forward(method, path, dump(data))
    except StrictJSONError as err:
        return Reject(403, str(err))


def tags_answer(policy: Mapping[str, ModelPolicy]) -> Answer:
    """``GET /api/tags`` from the policy: only the run's generator + embed tags (D1071)."""
    models = [{"name": tag, "model": tag} for tag in sorted(policy)]
    return Answer(200, json.dumps({"models": models}).encode())


def is_reload(response: bytes) -> bool:
    """True when any JSON line of an Ollama response reports ``load_duration`` > 1 s (in ns)."""
    for line in response.splitlines():
        try:
            item = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        duration = item.get("load_duration") if isinstance(item, dict) else None
        if isinstance(duration, int | float) and duration > RELOAD_NS:
            return True
    return False
