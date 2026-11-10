"""``llm-proxy``: the candidate's only route to the Ollama server (T6.2a S4b; D206, D242, ADR-0018).

A trusted stdlib HTTP server in a normal container on ``gate-net`` + ``proxy-egress``. It listens on
``0.0.0.0:11500`` inside the container (reached as ``http://llm-proxy:11500``; no host port) and
forwards only what :func:`llm_proxy_policy.decide` allows to ``LLM_PROXY_UPSTREAM`` (default
``http://172.17.0.1:11434``, the tunnel to the one Ollama server). ``GET /health`` returns the
cumulative counters ``{"model_reloads", "upstream_errors", "requests"}`` (interfaces 1.5, N6.4).

Environment: ``PRUEFSTAND_CANDIDATE_API_KEY`` (required, never logged), ``LLM_PROXY_POLICY`` (JSON
``{tag: {"role", "options", "option_bounds"}}`` for the run's generator + embedding tags, written by
the orchestrator from ``infra/gpu/models.yaml``), ``LLM_PROXY_UPSTREAM``. Bodies are never logged.
"""

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from urllib.parse import urlsplit

from llm_proxy_policy import Forward, ModelPolicy, PolicyError, build_policy, decide, is_reload

DEFAULT_LISTEN = ("0.0.0.0", 11500)  # noqa: S104 - container-internal port on gate-net, no host port (D242)
DEFAULT_UPSTREAM = "http://172.17.0.1:11434"
MAX_BODY_BYTES = 4 * 1024 * 1024
UPSTREAM_TIMEOUT_S = 900.0
LOG = logging.getLogger("llm_proxy")


@dataclass
class Counters:
    """Cumulative counters since start; thread-safe."""

    model_reloads: int = 0
    upstream_errors: int = 0
    requests: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(
        self, *, reload: bool = False, upstream_error: bool = False, request: bool = False
    ) -> None:
        """Increment the named counters by one."""
        with self._lock:
            self.model_reloads += int(reload)
            self.upstream_errors += int(upstream_error)
            self.requests += int(request)

    def snapshot(self) -> dict[str, int]:
        """The ``/health`` body: exactly ``model_reloads``, ``upstream_errors``, ``requests``."""
        with self._lock:
            return {
                "model_reloads": self.model_reloads,
                "upstream_errors": self.upstream_errors,
                "requests": self.requests,
            }


@dataclass(frozen=True)
class ProxyConfig:
    """Everything a handler needs: key, policy, upstream base URL and limits."""

    key: str
    policy: Mapping[str, ModelPolicy]
    upstream: str = DEFAULT_UPSTREAM
    max_body: int = MAX_BODY_BYTES
    timeout_s: float = UPSTREAM_TIMEOUT_S


def check_upstream(url: str) -> str:
    """Return ``url`` without a trailing slash; raise ``ValueError`` unless it is ``http://host:port``."""
    parts = urlsplit(url)
    if parts.scheme != "http" or not parts.hostname or parts.path not in ("", "/") or parts.query:
        msg = "LLM_PROXY_UPSTREAM must be http://<host>:<port>"
        raise ValueError(msg)
    return url.rstrip("/")


def policy_from_json(text: str) -> dict[str, ModelPolicy]:
    """Parse ``LLM_PROXY_POLICY`` (``{tag: catalogue fields}``) through :func:`build_policy`."""
    raw = json.loads(text)
    if not isinstance(raw, dict) or not raw:
        msg = "LLM_PROXY_POLICY must be a non-empty JSON object"
        raise PolicyError(msg)
    entries = [{**fields, "tag": tag} for tag, fields in raw.items() if isinstance(fields, dict)]
    return build_policy(entries, list(raw))


def config_from_env(env: Mapping[str, str]) -> ProxyConfig:
    """Build the config from the container environment; raise ``ValueError`` when incomplete."""
    key = env.get("PRUEFSTAND_CANDIDATE_API_KEY", "")
    if not key:
        msg = "PRUEFSTAND_CANDIDATE_API_KEY is not set"
        raise ValueError(msg)
    policy = policy_from_json(env.get("LLM_PROXY_POLICY", ""))
    upstream = check_upstream(env.get("LLM_PROXY_UPSTREAM", DEFAULT_UPSTREAM))
    return ProxyConfig(key=key, policy=policy, upstream=upstream)


class ProxyHandler(BaseHTTPRequestHandler):
    """Request handler; :func:`make_handler` binds ``cfg`` and ``counters``."""

    cfg: ClassVar[ProxyConfig]
    counters: ClassVar[Counters]
    protocol_version = "HTTP/1.1"
    server_version = "llm-proxy"

    def do_GET(self) -> None:
        """Serve ``/health`` or route the request through :func:`decide`."""
        if self.path == "/health":
            self._send(200, json.dumps(self.counters.snapshot()).encode())
            return
        self._handle(b"")

    def do_POST(self) -> None:
        """Cap the body size, then route the request through :func:`decide`."""
        length = self._length()
        if length is None or not 0 <= length <= self.cfg.max_body:
            self.close_connection = True
            self._error(403, "body too large or without Content-Length")
            return
        self._handle(self.rfile.read(length))

    def do_PUT(self) -> None:
        """Always 403."""
        self._refuse()

    def do_DELETE(self) -> None:
        """Always 403."""
        self._refuse()

    def do_HEAD(self) -> None:
        """Always 403."""
        self._refuse()

    def _refuse(self) -> None:
        self.close_connection = True
        self._error(403, f"path not allowed: {self.command} {self.path}")

    def _length(self) -> int | None:
        try:
            return int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None

    def _handle(self, body: bytes) -> None:
        verdict = decide(
            self.command,
            self.path,
            auth=self.headers.get("Authorization"),
            body=body,
            key=self.cfg.key,
            policy=self.cfg.policy,
        )
        if isinstance(verdict, Forward):
            self._forward(verdict)
        else:
            self._error(verdict.status, verdict.reason)

    def _forward(self, fwd: Forward) -> None:
        self.counters.add(request=True)
        status, payload = forward(self.cfg, fwd)
        if status >= 500:
            self.counters.add(upstream_error=True)
        elif is_reload(payload):
            self.counters.add(reload=True)
        self._send(status, payload)

    def _error(self, status: int, reason: str) -> None:
        self._send(status, json.dumps({"error": reason}).encode())

    def _send(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002, ARG002 - stdlib signature
        """Log method and path only: never a body, a query or a header."""
        LOG.info("%s %s", self.command, self.path.split("?", 1)[0])


def make_handler(cfg: ProxyConfig, counters: Counters) -> type[ProxyHandler]:
    """A request handler class bound to ``cfg`` and ``counters``."""
    return type("BoundProxyHandler", (ProxyHandler,), {"cfg": cfg, "counters": counters})


def forward(cfg: ProxyConfig, fwd: Forward) -> tuple[int, bytes]:
    """Send ``fwd`` upstream; return ``(status, body)``, or ``(502, error)`` when unreachable."""
    headers = {"Content-Type": "application/json"} if fwd.body is not None else {}
    req = urllib.request.Request(  # noqa: S310 - scheme fixed to http by check_upstream
        cfg.upstream + fwd.path, data=fwd.body, method=fwd.method, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:  # noqa: S310 - see above
            return int(resp.status), bytes(resp.read())
    except urllib.error.HTTPError as err:
        return int(err.code), bytes(err.read())
    except (urllib.error.URLError, OSError) as err:
        LOG.warning("upstream unreachable: %s", type(err).__name__)
        return 502, json.dumps({"error": "upstream unreachable"}).encode()


def serve(cfg: ProxyConfig, address: tuple[str, int] = DEFAULT_LISTEN) -> ThreadingHTTPServer:
    """Create (not start) the threaded server; the caller runs ``serve_forever``."""
    return ThreadingHTTPServer(address, make_handler(cfg, Counters()))


def main() -> None:
    """Container entry point: config from the environment, serve on ``0.0.0.0:11500``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = serve(config_from_env(os.environ))
    LOG.info("llm-proxy listening on %s:%d", *DEFAULT_LISTEN)
    server.serve_forever()


if __name__ == "__main__":
    main()
