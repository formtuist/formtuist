"""Publish a local textual-serve form through a bitbang WebRTC tunnel."""

import asyncio
import contextlib
import gzip
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from bitbang import BitBangWSGI

# response and proxy tuning constants
CHUNK_SIZE = 32768
GZIP_MIN_SIZE = 1024
POLL_INTERVAL_SECONDS = 0.5
STARTUP_TIMEOUT_SECONDS = 30
REQUEST_TIMEOUT_SECONDS = 30
HTML_CONTENT_TYPE = "text/html"
HTTP_SCHEME = "http://"
GZIP_ENCODING = "gzip"
IDENTITY_ENCODING = "identity"
BAD_GATEWAY_STATUS = "502 Bad Gateway"
TEXT_PLAIN_CONTENT_TYPE = "text/plain"

# content types that are worth compressing before sending through WebRTC
COMPRESSIBLE_PREFIXES = ("text/",)
COMPRESSIBLE_TYPES = {
    "application/javascript",
    "application/json",
    "application/manifest+json",
    "application/xhtml+xml",
    "application/xml",
    "font/otf",
    "font/ttf",
    "image/svg+xml",
}

# common CA bundle locations, including the location used by NixOS
CA_BUNDLE_CANDIDATES = (
    Path("/etc/ssl/certs/ca-certificates.crt"),
    Path("/etc/ssl/certs/ca-bundle.crt"),
)
SSL_CERT_FILE = "SSL_CERT_FILE"
SSL_CERT_DIR = "SSL_CERT_DIR"

# arguments used to launch the local formtuist server in a child process
PYTHON_MODULE_FLAG = "-m"
CLI_MODULE = "formtuist.cli"
SERVE_COMMAND = "serve"
HOST_OPTION = "--host"
PORT_OPTION = "--port"
DB_DIR_OPTION = "--db-dir"
DATABASE_NAME_OPTION = "--database-name"
CODE_DIR_OPTION = "--code-dir"

# adapter configuration
BITBANG_PROGRAM_NAME = "formtuist"

# admission-control tuning for the bitbang tunnel
#
# bitbang registers a peer when the signaling offer arrives but marks it
# authenticated only once the SWSP connect message arrives over the data
# channel. That window spans the whole ICE, DTLS, and SCTP setup, and at
# least RELAY_GRACE (8 seconds) whenever the TURN path is used. bitbang's own
# _count_unauth_live counts every in-flight peer against MAX_UNAUTH_PEERS
# (10), so it behaves as an admission limit of ten concurrent connection
# setups rather than ten visitors. A class opening one link at the same
# moment exceeds it immediately, and the rejection is silent: the adapter
# returns without answering the offer, so the browser waits on "Loading..."
# forever. Peers are removed only on reconnect or adapter close, so ten
# abandoned loads then lock out every later visitor for the life of the
# process.
#
# FormtuistBitBang corrects both behaviours without modifying bitbang.
# Admission counts only peers that have stayed unauthenticated for
# STUCK_SESSION_SECONDS, and a reaper forgets peers whose connection has
# ended as well as handshakes that never connected within
# STALE_HANDSHAKE_SECONDS. A connected peer that has not authenticated yet is
# a visitor at the PIN prompt, so the reaper leaves it alone.
STUCK_SESSION_SECONDS = 45.0
STALE_HANDSHAKE_SECONDS = 60.0
REAP_INTERVAL_SECONDS = 10.0
SEND_DEADLINE_SECONDS = 15.0
SEND_POLL_SECONDS = 0.01

# keys and states that bitbang and aiortc use to describe each peer
REQUEST_CLIENT_ID_KEY = "client_id"
PEER_AUTHENTICATED_KEY = "authenticated"
PEER_CONNECTION_KEY = "pc"
PEER_RELAY_GATE_KEY = "relay_gate_task"
CONNECTION_STATE_ATTRIBUTE = "connectionState"
SCTP_FLIGHT_SIZE_ATTRIBUTE = "_flight_size"
CONNECTED_STATE = "connected"
CLOSED_STATE = "closed"
FAILED_STATE = "failed"
OPEN_CHANNEL_STATE = "open"

# aiortc never leaves these states, and it has no "disconnected" state
TERMINAL_CONNECTION_STATES = frozenset({CLOSED_STATE, FAILED_STATE})
SEND_STALLED_MESSAGE = "peer did not drain its data channel within {:.0f}s"

# bitbang keys a request that arrives without a client id under None
ClientId = str | None


class SendStalledError(TimeoutError):
    """Signal that a peer stopped draining its data channel."""


def _connection_state(peer: dict[str, Any]) -> str:
    """Return a peer's connection state, treating a missing one as closed."""
    state: str = getattr(
        peer.get(PEER_CONNECTION_KEY),
        CONNECTION_STATE_ATTRIBUTE,
        CLOSED_STATE,
    )
    return state


class FormtuistBitBang(BitBangWSGI):
    """Admit bursts of visitors and reclaim peers that bitbang would leak."""

    stuck_after = STUCK_SESSION_SECONDS
    stale_after = STALE_HANDSHAKE_SECONDS
    reap_interval = REAP_INTERVAL_SECONDS
    send_deadline = SEND_DEADLINE_SECONDS

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create the adapter and its bookkeeping for session ages."""
        super().__init__(*args, **kwargs)
        self._first_seen: dict[ClientId, float] = {}
        self._reaper: asyncio.Task[None] | None = None
        self.reaped_sessions = 0

    def setup_peer_connection(self, pc: Any, client_id: ClientId) -> None:
        """Stamp a peer at the moment bitbang admits and registers it."""
        super().setup_peer_connection(pc, client_id)
        # bitbang stores the peer right after this hook returns, with no
        # await in between, so a stamp never outlives or predates its peer
        self._first_seen[client_id] = time.monotonic()

    async def handle_request(self, ws: Any, message: dict[str, Any]) -> None:
        """Retire a reconnecting client's old peer, then delegate."""
        client_id = message.get(REQUEST_CLIENT_ID_KEY)
        previous = self.peers.get(client_id)
        # bitbang's own cleanup awaits the old close and then deletes by key,
        # which raises KeyError if the reaper forgot the peer in the meantime
        if previous is not None:
            await self._drop_peer(client_id, previous)
        self._ensure_reaper()
        await super().handle_request(ws, message)

    def _add_ice_candidate(self, data: dict[str, Any]) -> None:
        """Add a browser's ICE candidate unless it cannot be parsed."""
        # bitbang parses candidates inside its signaling loop with no error
        # handling, so an empty end-of-candidates marker or any malformed
        # candidate would drop the publisher off the signaling server, and
        # every new visitor would see "Device not found" until it registered
        # again; losing one candidate affects only the browser that sent it
        with contextlib.suppress(Exception):
            super()._add_ice_candidate(data)

    async def close(self) -> None:
        """Stop the reaper, then close and forget every peer."""
        reaper, self._reaper = self._reaper, None
        if reaper is not None and not reaper.done():
            reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reaper
        for client_id, peer in list(self.peers.items()):
            await self._drop_peer(client_id, peer)
        await super().close()
        self._first_seen.clear()

    def _count_unauth_live(self) -> int:
        """Count unauthenticated peers stuck past the admission threshold."""
        now = time.monotonic()
        return sum(
            1
            for client_id, peer in list(self.peers.items())
            if not peer.get(PEER_AUTHENTICATED_KEY)
            and _connection_state(peer) not in TERMINAL_CONNECTION_STATES
            and self._age(client_id, now) >= self.stuck_after
        )

    def _age(self, client_id: ClientId, now: float) -> float:
        """Return how long a peer has been registered, stamping it if new."""
        return now - self._first_seen.setdefault(client_id, now)

    def _is_reapable(
        self, client_id: ClientId, peer: dict[str, Any], now: float
    ) -> bool:
        """Report whether a peer can never be served again."""
        state = _connection_state(peer)
        if state in TERMINAL_CONNECTION_STATES:
            return True
        if peer.get(PEER_AUTHENTICATED_KEY) or state == CONNECTED_STATE:
            return False
        return self._age(client_id, now) >= self.stale_after

    def _ensure_reaper(self) -> None:
        """Start the reaper once, on the event loop that serves requests."""
        if self._reaper is None or self._reaper.done():
            self._reaper = asyncio.create_task(self._reap_loop())

    async def _reap_loop(self) -> None:
        """Periodically forget peers that can never be served again."""
        while True:
            await asyncio.sleep(self.reap_interval)
            await self.reap_once()

    async def reap_once(self) -> int:
        """Close and forget unservable peers and return how many went."""
        now = time.monotonic()
        doomed = [
            (client_id, peer)
            for client_id, peer in list(self.peers.items())
            if self._is_reapable(client_id, peer, now)
        ]
        dropped = 0
        for client_id, peer in doomed:
            if await self._drop_peer(client_id, peer):
                dropped += 1
        # a stamp with no peer belongs to a request that never registered one
        for client_id in set(self._first_seen) - set(self.peers):
            del self._first_seen[client_id]
        self.reaped_sessions += dropped
        return dropped

    async def _drop_peer(
        self, client_id: ClientId, peer: dict[str, Any]
    ) -> bool:
        """Close and forget a peer unless a newer one has replaced it."""
        # the reaper awaits between drops, so a reconnect may have registered
        # a fresh peer under the same client id, and that peer must survive
        if self.peers.get(client_id) is not peer:
            return False
        del self.peers[client_id]
        self._first_seen.pop(client_id, None)
        gate = peer.get(PEER_RELAY_GATE_KEY)
        if gate is not None and not gate.done():
            gate.cancel()
        pc = peer.get(PEER_CONNECTION_KEY)
        if pc is not None:
            # closing is best effort because the peer is already forgotten
            with contextlib.suppress(Exception):
                await pc.close()
        return True

    async def _send_with_backpressure(
        self, channel: Any, frame: bytes, limit: int, sctp: Any
    ) -> None:
        """Send a frame once the peer drains, failing loudly if it stalls."""
        deadline = time.monotonic() + self.send_deadline
        while True:
            # a closed channel ends bitbang's send loop on its next check
            if channel.readyState != OPEN_CHANNEL_STATE:
                return
            flight = getattr(sctp, SCTP_FLIGHT_SIZE_ATTRIBUTE, 0)
            if channel.bufferedAmount + flight <= limit:
                break
            # skipping a frame would corrupt the stream, so raise and let
            # bitbang finish the stream with an error response instead
            if time.monotonic() >= deadline:
                raise SendStalledError(
                    SEND_STALLED_MESSAGE.format(self.send_deadline)
                )
            await asyncio.sleep(SEND_POLL_SECONDS)
        channel.send(frame)


class RewritingProxy:
    """Proxy a local textual-serve instance as a WSGI application."""

    def __init__(self, target: str) -> None:
        """Store the local target and its absolute URL origin."""
        if not target.startswith(HTTP_SCHEME):
            target = f"{HTTP_SCHEME}{target}"
        self.target = target.rstrip("/")
        self._origin = self.target

    def __call__(
        self, environ: dict[str, Any], start_response: Any
    ) -> Iterable[bytes]:
        """Proxy one request and rewrite textual-serve HTML URLs."""
        method = environ["REQUEST_METHOD"]
        path = environ.get("PATH_INFO", "/")
        query = environ.get("QUERY_STRING", "")
        url = f"{self.target}{path}"
        if query:
            url += f"?{query}"
        headers = {
            key[5:].replace("_", "-").title(): value
            for key, value in environ.items()
            if key.startswith("HTTP_")
        }
        if environ.get("CONTENT_TYPE"):
            headers["Content-Type"] = environ["CONTENT_TYPE"]
        headers["Accept-Encoding"] = IDENTITY_ENCODING
        body = None
        content_length = environ.get("CONTENT_LENGTH")
        if content_length and int(content_length) > 0:
            body = environ["wsgi.input"].read(int(content_length))
        request = urllib.request.Request(
            url, data=body, headers=headers, method=method
        )
        try:
            response = urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except urllib.error.HTTPError as error:
            response = error
        except Exception as error:
            start_response(
                BAD_GATEWAY_STATUS, [("Content-Type", TEXT_PLAIN_CONTENT_TYPE)]
            )
            return [f"proxy error: {error}".encode()]
        status = f"{response.status} {response.reason}"
        content_type = response.headers.get("Content-Type", "")
        accept_encoding = environ.get("HTTP_ACCEPT_ENCODING", "").lower()
        wants_gzip = GZIP_ENCODING in accept_encoding
        if response.status in (204, 304, 101):
            start_response(status, list(response.headers.items()))
            return _iter_chunks(response)
        is_html = HTML_CONTENT_TYPE in content_type
        should_buffer = is_html or (
            wants_gzip and _is_compressible(content_type)
        )
        if should_buffer:
            data = response.read()
            response.close()
            if is_html:
                data = data.replace(self._origin.encode(), b"")
            return self._respond(
                start_response,
                status,
                response.headers,
                data,
                compress=wants_gzip,
            )
        start_response(status, list(response.headers.items()))
        return _iter_chunks(response)

    @staticmethod
    def _respond(
        start_response: Any,
        status: str,
        upstream_headers: Any,
        data: bytes,
        compress: bool = False,
    ) -> list[bytes]:
        """Return a buffered response with an exact content length."""
        encoding = None
        if compress and len(data) >= GZIP_MIN_SIZE:
            compressed = gzip.compress(data, compresslevel=6)
            if len(compressed) < len(data):
                data = compressed
                encoding = GZIP_ENCODING
        output_headers = []
        skipped_headers = {
            "content-length",
            "transfer-encoding",
            "content-encoding",
            "etag",
            "content-md5",
            "connection",
            "keep-alive",
            "proxy-connection",
        }
        for key, value in upstream_headers.items():
            if key.lower() not in skipped_headers:
                output_headers.append((key, value))
        if encoding:
            output_headers.append(("Content-Encoding", encoding))
            output_headers.append(("Vary", "Accept-Encoding"))
        output_headers.append(("Content-Length", str(len(data))))
        start_response(status, output_headers)
        return [data]


def _is_compressible(content_type: str) -> bool:
    """Return whether a response content type benefits from gzip."""
    media_type = content_type.split(";", maxsplit=1)[0].strip().lower()
    return media_type.startswith(COMPRESSIBLE_PREFIXES) or media_type in (
        COMPRESSIBLE_TYPES
    )


def _iter_chunks(response: Any) -> Iterable[bytes]:
    """Yield an upstream response body in bounded chunks."""
    try:
        while True:
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
    except Exception:
        return
    finally:
        response.close()


def ensure_ca_store() -> None:
    """Configure a system CA bundle when Python has no CA setting."""
    if os.environ.get(SSL_CERT_FILE) or os.environ.get(SSL_CERT_DIR):
        return
    for candidate in CA_BUNDLE_CANDIDATES:
        if candidate.is_file():
            os.environ[SSL_CERT_FILE] = str(candidate)
            return


def wait_for_server(host: str, port: int) -> None:
    """Wait for the local server to answer or raise a startup error."""
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"{HTTP_SCHEME}{host}:{port}/",
                timeout=1,
            ):
                return
        except Exception:
            time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError(
        f"local server on {host}:{port} did not start within "
        f"{STARTUP_TIMEOUT_SECONDS}s"
    )


def build_serve_command(  # noqa: PLR0913, PLR0917
    form_path: Path,
    host: str,
    port: int,
    db_dir: Path | None = None,
    database_name: str | None = None,
    code_dir: Path | None = None,
) -> list[str]:
    """Build the child-process command that runs textual-serve."""
    command = [
        sys.executable,
        PYTHON_MODULE_FLAG,
        CLI_MODULE,
        SERVE_COMMAND,
        str(form_path),
        HOST_OPTION,
        host,
        PORT_OPTION,
        str(port),
    ]
    if db_dir is not None:
        command.extend([DB_DIR_OPTION, str(db_dir)])
    if database_name is not None:
        command.extend([DATABASE_NAME_OPTION, database_name])
    if code_dir is not None:
        command.extend([CODE_DIR_OPTION, str(code_dir)])
    return command


def _stop_process(process: subprocess.Popen[Any]) -> None:
    """Terminate a child process and force it down if necessary."""
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def publish_form(  # noqa: PLR0913, PLR0917
    form_path: Path,
    host: str,
    port: int,
    signaling: str,
    pin: str | None,
    ephemeral: bool,
    db_dir: Path | None = None,
    database_name: str | None = None,
    code_dir: Path | None = None,
) -> None:
    """Run textual-serve locally and expose it through bitbang."""
    ensure_ca_store()
    command = build_serve_command(
        form_path,
        host,
        port,
        db_dir,
        database_name,
        code_dir,
    )
    serve_process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(host, port)
        target = f"{host}:{port}"
        adapter = FormtuistBitBang(
            RewritingProxy(target),
            program_name=BITBANG_PROGRAM_NAME,
            server=signaling,
            pin=pin,
            ephemeral=ephemeral,
        )
        adapter.ws_target = target
        adapter.run()
    finally:
        _stop_process(serve_process)
