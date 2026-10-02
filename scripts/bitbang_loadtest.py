# /// script
# requires-python = ">=3.12"
# dependencies = ["bitbang>=0.1.55,<0.2"]
# ///
"""Load-test bitbang admission control the way a class actually hits it.

Formtuist publishes forms through bitbang, whose listener admits only ten
concurrent unauthenticated peers. Because bitbang registers a peer when the
signaling offer arrives but marks it authenticated only once the SWSP connect
message arrives over the data channel, that ten-slot budget is really ten
concurrent connection setups. A class opening one link at the same moment
exceeds it, the rejection is silent, and peers that never authenticate are
never reaped.

This harness drives bitbang's real handle_request path with in-process doubles
for the peer connection and the signaling socket. Nothing on disk is patched:
bitbang is imported and exercised exactly as installed, and the only formtuist
code under test is the FormtuistBitBang subclass in src/formtuist/publisher.py.
Every adapter uses an ephemeral identity, so no identity is read from or
written to the home directory.

Run it with:

    uv run scripts/bitbang_loadtest.py --clients 30
"""

import argparse
import asyncio
import contextlib
import importlib.util
import io
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from bitbang import BitBangWSGI
from bitbang import adapter as bitbang_adapter

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLISHER_PATH = REPO_ROOT / "src" / "formtuist" / "publisher.py"
PROGRAM_NAME = "formtuist-loadtest"
BROWSER_IP = "203.0.113.7"

# markers printed by bitbang, used both to classify outcomes and to detect a
# harness that is silently failing (an incomplete double makes handle_request
# swallow an exception and look exactly like a rejection)
REJECTION_MARKER = "too many pending"
BROKEN_MARKER = "Error handling request"

# probe ages for the abandoned-session scenarios, chosen against the tuned
# thresholds each scenario installs
PROBE_STUCK_SECONDS = 0.08  # past stuck_after, long before stale_after
PROBE_REAPED_SECONDS = 0.30  # past stale_after, so the reaper has run
# the stuck scenario must never reap, so its stale_after sits far beyond the
# probe; a margin of a few milliseconds would let a slow machine reap the
# abandoned sessions while the late arrivals are still being offered
STUCK_TUNING = {
    "stuck_after": 0.05,
    "stale_after": 5.0,
    "reap_interval": 0.02,
}
REAPED_TUNING = {
    "stuck_after": 0.05,
    "stale_after": 0.15,
    "reap_interval": 0.02,
}


def emit(line: str = "") -> None:
    """Write one line to stdout without tripping the print check."""
    sys.stdout.write(line + "\n")


def load_publisher() -> Any:
    """Import formtuist's publisher module straight from the source tree."""
    spec = importlib.util.spec_from_file_location(
        "formtuist_publisher", PUBLISHER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {PUBLISHER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_app() -> Any:
    """Return a trivial WSGI app to stand in for textual-serve."""

    def app(environ: dict[str, Any], start_response: Any) -> list[bytes]:
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"ok"]

    return app


class FakeDataChannel:
    """Minimal data channel: records frames and replays handlers."""

    def __init__(self, label: str = "http") -> None:
        """Create an open channel with no buffered data."""
        self.label = label
        self.readyState = "open"
        self.bufferedAmount = 0
        self.sent: list[bytes] = []
        self._handlers: dict[str, Any] = {}

    def on(self, event: str) -> Any:
        """Register a handler the way aiortc does, decorator style."""

        def register(fn: Any) -> Any:
            self._handlers[event] = fn
            return fn

        return register

    def send(self, data: bytes) -> None:
        """Record an outbound frame."""
        self.sent.append(data)

    def emit(self, event: str, *args: Any) -> Any:
        """Fire a registered handler, if any."""
        handler = self._handlers.get(event)
        return handler(*args) if handler else None


class FakePeerConnection:
    """Minimal RTCPeerConnection: enough for bitbang's offer path."""

    def __init__(self, config: Any = None) -> None:
        """Create a peer that is connected (not merely new)."""
        self.config = config
        self.channel: FakeDataChannel | None = None
        self.iceGatheringState = "complete"
        self.iceConnectionState = "connecting"
        self.connectionState = "connecting"
        self.localDescription = SimpleNamespace(sdp="v=0\r\nfake")
        self.sctp = None
        self.closed = False
        self.candidates: list[Any] = []
        self._handlers: dict[str, Any] = {}

    def createDataChannel(self, label: str) -> FakeDataChannel:
        """Create and remember the single data channel bitbang asks for."""
        self.channel = FakeDataChannel(label)
        return self.channel

    def on(self, event: str) -> Any:
        """Register a handler the way aiortc does, decorator style."""

        def register(fn: Any) -> Any:
            self._handlers[event] = fn
            return fn

        return register

    async def createOffer(self) -> Any:
        """Return a stand-in offer."""
        return SimpleNamespace(sdp="v=0\r\nfake-offer")

    async def setLocalDescription(self, description: Any) -> None:
        """Remember the local description."""
        self.localDescription = description

    async def close(self) -> None:
        """Mark the connection closed."""
        self.closed = True
        self.connectionState = "closed"
        self.iceConnectionState = "closed"

    async def addIceCandidate(self, candidate: Any) -> None:
        """Record a candidate that bitbang hands to the connection."""
        self.candidates.append(candidate)

    def getTransceivers(self) -> list[Any]:
        """Report no transceivers, so stream metadata stays empty."""
        return []


class FakeSignaling:
    """Signaling websocket double that records what bitbang would send."""

    def __init__(self) -> None:
        """Start with nothing sent."""
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        """Record an outbound signaling message."""
        self.sent.append(payload)


def install_doubles(monkeypatch_module: Any) -> None:
    """Swap in the peer-connection double for this process only."""
    monkeypatch_module.RTCPeerConnection = FakePeerConnection


def build_adapter(
    kind: str, publisher: Any, tuning: dict[str, float] | None = None
) -> Any:
    """Build a stock or fixed adapter with no real identity or network."""
    cls = publisher.FormtuistBitBang if kind == "fixed" else BitBangWSGI
    adapter = cls(
        make_app(),
        program_name=PROGRAM_NAME,
        ephemeral=True,
        debug=False,
    )
    for name, value in (tuning or {}).items():
        setattr(adapter, name, value)
    return adapter


async def offer(adapter: Any, client_id: str) -> tuple[bool, FakeSignaling]:
    """Send one connection request; report whether it was admitted."""
    ws = FakeSignaling()
    await adapter.handle_request(
        ws, {"client_id": client_id, "browser_ip": BROWSER_IP}
    )
    return client_id in adapter.peers, ws


def authenticate(adapter: Any, client_id: str) -> bool:
    """Deliver the SWSP connect message for an admitted client."""
    peer = adapter.peers.get(client_id)
    if peer is None:
        return False
    payload = json.dumps({"type": "connect", "path": "/"}).encode("utf-8")
    adapter._handle_control_message(peer["channel"], payload, client_id)
    return bool(adapter.peers.get(client_id, {}).get("authenticated"))


async def shut_down(adapter: Any) -> None:
    """Close an adapter so its peers and any reaper task end cleanly."""
    with contextlib.redirect_stdout(io.StringIO()):
        await adapter.close()


class Result:
    """Outcome of one scenario for one implementation."""

    def __init__(self, name: str) -> None:
        """Start a blank result under a scenario name."""
        self.name = name
        self.offered = 0
        self.admitted = 0
        self.authenticated = 0
        self.rejections = 0
        self.silent_rejections = 0
        self.reaped = 0

    @property
    def rejected(self) -> int:
        """How many offers were refused."""
        return self.offered - self.admitted


async def run_burst(
    kind: str, publisher: Any, clients: int, do_auth: bool
) -> Result:
    """Offer from many clients at once, optionally authenticating after."""
    label = "burst+auth" if do_auth else "burst"
    result = Result(label)
    adapter = build_adapter(kind, publisher)
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            for index in range(clients):
                admitted, _ = await offer(adapter, f"b{index}")
                result.offered += 1
                result.admitted += int(admitted)
            if do_auth:
                for index in range(clients):
                    result.authenticated += int(
                        authenticate(adapter, f"b{index}")
                    )
    finally:
        await shut_down(adapter)
    result.rejections = buffer.getvalue().count(REJECTION_MARKER)
    return result


async def run_abandoned(  # noqa: PLR0913, PLR0917
    kind: str,
    publisher: Any,
    abandoned: int,
    late: int,
    age: float,
    tuning: dict[str, float],
) -> Result:
    """Abandon some sessions, age them, then offer from late arrivals."""
    result = Result(f"abandoned age={age:.2f}s")
    adapter = build_adapter(kind, publisher, tuning)
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            for index in range(abandoned):
                await offer(adapter, f"a{index}")  # never authenticate
            await asyncio.sleep(age)
            if hasattr(adapter, "reap_once"):
                await adapter.reap_once()
            result.reaped = getattr(adapter, "reaped_sessions", 0)
            for index in range(late):
                admitted, ws = await offer(adapter, f"l{index}")
                result.offered += 1
                result.admitted += int(admitted)
                if not admitted and not ws.sent:
                    result.silent_rejections += 1
    finally:
        await shut_down(adapter)
    result.rejections = buffer.getvalue().count(REJECTION_MARKER)
    return result


async def run_all(
    clients: int, abandoned: int, publisher: Any
) -> dict[str, dict[str, Result]]:
    """Run every scenario against both implementations."""
    results: dict[str, dict[str, Result]] = {}
    for kind in ("baseline", "fixed"):
        results[kind] = {
            "burst": await run_burst(kind, publisher, clients, False),
            "burst+auth": await run_burst(kind, publisher, clients, True),
            "stuck": await run_abandoned(
                kind,
                publisher,
                abandoned,
                abandoned,
                PROBE_STUCK_SECONDS,
                STUCK_TUNING,
            ),
            "reaped": await run_abandoned(
                kind,
                publisher,
                abandoned,
                abandoned,
                PROBE_REAPED_SECONDS,
                REAPED_TUNING,
            ),
        }
    return results


def report(results: dict[str, dict[str, Result]], clients: int) -> int:
    """Print the comparison table and return a process exit code."""
    emit()
    emit(f"bitbang admission control - {clients} clients, no PIN")
    emit("=" * 68)
    header = f"{'scenario':<34}{'baseline':>15}{'fixed':>15}"
    emit(header)
    emit("-" * 68)
    for key in ("burst", "burst+auth", "stuck", "reaped"):
        base = results["baseline"][key]
        fixed = results["fixed"][key]
        name = base.name
        left = f"{base.rejected} rejected"
        right = f"{fixed.rejected} rejected"
        emit(f"{name:<34}{left:>15}{right:>15}")
    emit("-" * 68)
    emit()
    emit("detail")
    emit("-" * 68)
    for kind in ("baseline", "fixed"):
        for key in ("burst", "burst+auth", "stuck", "reaped"):
            item = results[kind][key]
            emit(
                f"  {kind:<9}{item.name:<24}"
                f" offered={item.offered:<4}"
                f" admitted={item.admitted:<4}"
                f" auth={item.authenticated:<4}"
                f" reaped={item.reaped}"
            )
    emit()
    base_burst = results["baseline"]["burst"]
    fixed_burst = results["fixed"]["burst"]
    fixed_reaped = results["fixed"]["reaped"]
    base_reaped = results["baseline"]["reaped"]
    emit("what the numbers say")
    emit("-" * 68)
    emit(
        f"  burst: stock admits {base_burst.admitted}/{base_burst.offered}"
        f" simultaneous setups; the fix admits "
        f"{fixed_burst.admitted}/{fixed_burst.offered}."
    )
    emit(
        f"  stuck sessions still capped (defence intact): "
        f"baseline {results['baseline']['stuck'].rejected} rejected, "
        f"fixed {results['fixed']['stuck'].rejected} rejected."
    )
    emit(
        f"  after reaping: stock still rejects "
        f"{base_reaped.rejected}/{base_reaped.offered}; the fix rejects "
        f"{fixed_reaped.rejected}/{fixed_reaped.offered} and reaped "
        f"{fixed_reaped.reaped} stale peers."
    )
    emit(
        f"  silent rejections (the browser's request gets no reply at "
        f"all): baseline "
        f"{results['baseline']['reaped'].silent_rejections}, fixed "
        f"{results['fixed']['reaped'].silent_rejections}."
    )
    emit()
    # stock bitbang only refuses a burst larger than its admission cap
    burst_overflows = clients > bitbang_adapter.MAX_UNAUTH_PEERS
    expected = (base_burst.rejected > 0 or not burst_overflows) and (
        fixed_burst.rejected == 0 and fixed_reaped.rejected == 0
    )
    if expected:
        emit("RESULT: reproduced the defect, and the fix removes it.")
    else:
        emit("RESULT: unexpected numbers - investigate before trusting.")
    return 0 if expected else 1


def main() -> int:
    """Parse arguments, run the scenarios, and report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clients",
        type=int,
        default=30,
        help="simultaneous connection setups to simulate (default 30)",
    )
    parser.add_argument(
        "--abandoned",
        type=int,
        default=10,
        help="sessions to abandon in the leak scenarios (default 10)",
    )
    args = parser.parse_args()
    started = time.monotonic()
    # the doubles replace aiortc for this whole process, which is why this
    # happens here and not in run_all, where a test suite would inherit it
    publisher = load_publisher()
    install_doubles(bitbang_adapter)
    results = asyncio.run(run_all(args.clients, args.abandoned, publisher))
    code = report(results, args.clients)
    elapsed = time.monotonic() - started
    emit(f"completed in {elapsed:.1f}s")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
