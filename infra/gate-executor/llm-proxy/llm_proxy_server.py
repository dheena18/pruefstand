"""Connection limits of ``llm-proxy`` (D1072, D1075): cap, reserved ``/health`` slots, deadline.

At most ``slots`` connections are served; ``reserve`` more may connect but are served only for
``GET /health``, so the orchestrator can always read the counters. Every connection carries one
request (``Connection: close``) and must deliver its request line, headers and body within
``deadline_s``, else its read side is shut down: a client trickling one byte per second cannot hold
a slot (the per-read idle timeout alone restarts with every byte). The deadline is cancelled once
the request is read, so a long upstream generation is never cut. Reserved slots get a much shorter
deadline (2 s) and go only to trusted peers (loopback: the container healthcheck, ``docker exec``),
and each untrusted peer may hold at most ``per_peer`` connections, so reconnecting tricklers on
``gate-net`` can neither take the reserve nor every slot (D1077, D1078).
"""

import logging
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import BaseServer

Request = socket.socket | tuple[bytes, socket.socket]
HEALTH_RESERVE = 2
LOG = logging.getLogger("llm_proxy")


class BoundedServer(ThreadingHTTPServer):
    """Threaded server with a connection cap, reserved health slots and a request deadline."""

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        slots: int,
        deadline_s: float,
        reserve_deadline_s: float,
        trusted_peers: frozenset[str],
        per_peer: int,
    ) -> None:
        self._slots = threading.BoundedSemaphore(slots)
        self._reserve = threading.BoundedSemaphore(HEALTH_RESERVE)
        self._deadline_s = deadline_s
        self._reserve_deadline_s = reserve_deadline_s
        self._local = threading.local()
        self._trusted = trusted_peers
        self._per_peer = per_peer
        self._peers: dict[str, int] = {}
        self._peers_lock = threading.Lock()
        super().__init__(address, handler)

    def process_request(self, request: Request, client_address: tuple[str, int]) -> None:
        """Serve on a normal slot, else (trusted peers only) a health-only slot, else close."""
        peer = str(client_address[0])
        trusted = peer in self._trusted
        if not self._admit_peer(peer, trusted=trusted):
            self.shutdown_request(request)
            return
        options = (
            ((self._slots, False), (self._reserve, True)) if trusted else ((self._slots, False),)
        )
        for slot, health_only in options:
            if slot.acquire(blocking=False):
                args = (request, client_address, slot, health_only)
                try:
                    threading.Thread(target=self._serve, args=args, daemon=True).start()
                except BaseException:  # D1078: a failed start must not leak the slot or the count
                    slot.release()
                    self._release_peer(peer)
                    raise
                return
        self._release_peer(peer)
        self.shutdown_request(request)

    def _admit_peer(self, peer: str, *, trusted: bool) -> bool:
        with self._peers_lock:
            count = self._peers.get(peer, 0)
            if not trusted and count >= self._per_peer:
                return False
            self._peers[peer] = count + 1
            return True

    def _release_peer(self, peer: str) -> None:
        with self._peers_lock:
            count = self._peers.get(peer, 1) - 1
            if count > 0:
                self._peers[peer] = count
            else:
                self._peers.pop(peer, None)

    def _serve(
        self,
        request: Request,
        client_address: tuple[str, int],
        slot: threading.BoundedSemaphore,
        health_only: bool,  # noqa: FBT001 - internal thread target
    ) -> None:
        sock = request if isinstance(request, socket.socket) else request[1]
        limit = self._reserve_deadline_s if health_only else self._deadline_s  # D1077
        timer = threading.Timer(limit, _cut, args=(sock,))
        self._local.health_only, self._local.timer = health_only, timer
        timer.start()
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            timer.cancel()
            self.shutdown_request(request)
            slot.release()
            self._release_peer(str(client_address[0]))

    def handle_error(self, request: Request, client_address: tuple[str, int]) -> None:  # noqa: ARG002
        """Log the error type only (no traceback, no request data)."""
        LOG.warning("client connection error: %s", type(sys.exception()).__name__)

    def health_only(self) -> bool:
        """True when the current connection holds a reserved (``/health`` only) slot."""
        return bool(getattr(self._local, "health_only", False))

    def request_read(self) -> None:
        """The request is fully read: cancel this connection's deadline."""
        timer = getattr(self._local, "timer", None)
        if isinstance(timer, threading.Timer):
            timer.cancel()


def _cut(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        return


def health_only(server: BaseServer) -> bool:
    """``server.health_only()`` for a :class:`BoundedServer`, else False."""
    return isinstance(server, BoundedServer) and server.health_only()


def request_read(server: BaseServer) -> None:
    """``server.request_read()`` for a :class:`BoundedServer`."""
    if isinstance(server, BoundedServer):
        server.request_read()
