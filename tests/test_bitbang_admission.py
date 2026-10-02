"""Tests for bitbang admission control in the formtuist publisher."""

import asyncio
import contextlib
import inspect
import io
import json
import struct
from collections.abc import Callable, Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from bitbang import adapter as bitbang_adapter

from formtuist import publisher
from scripts.bitbang_loadtest import (
    BROKEN_MARKER,
    BROWSER_IP,
    PROGRAM_NAME,
    REJECTION_MARKER,
    FakeDataChannel,
    FakePeerConnection,
    FakeSignaling,
    authenticate,
    make_app,
    offer,
)

# more simultaneous visitors than bitbang's own MAX_UNAUTH_PEERS allows
BURST_CLIENTS = 30
# exactly bitbang's MAX_UNAUTH_PEERS, used to show the cap still engages
CAPACITY = bitbang_adapter.MAX_UNAUTH_PEERS
# a buffer far larger than any backpressure limit, and one far smaller
HUGE_BACKLOG = 10**9
SMALL_LIMIT = 1024
# timings that keep the asynchronous tests fast but never flaky
FAST_INTERVAL = 0.01
LONG_DEADLINE = 60.0
WAIT_SECONDS = 5.0
NEVER = 10_000.0
# environment variables that locate the home directory on each platform
HOME_VARIABLES = ("HOME", "USERPROFILE")
# client identifiers and connection states used by the scenarios
CLIENT = "visitor"
OTHER_CLIENT = "neighbour"
LATE_CLIENT = "latecomer"
ORPHAN_CLIENT = "orphan"
CONNECTED = "connected"
CLOSED = "closed"
FAILED = "failed"
# a single WSGI request pushed through bitbang's real send loop
STREAM_ID = 1
FRAME_HEADER = "<IHH"
FRAME_HEADER_SIZE = 8
SERVER_ERROR = 500
GET_ROOT = {"method": "GET", "pathname": "/"}
FRAME = b"frame"
# ICE candidates as a browser trickles them through the signaling server
HOST_CANDIDATE = (
    "candidate:1 1 udp 2122260223 abcd-ef.local 54321 typ host generation 0"
)
END_OF_CANDIDATES = ""
GARBLED_CANDIDATE = "garbled"
MEDIA_ID = "0"
# bitbang treats the methods that FormtuistBitBang overrides as private, so a
# release may change them without notice; each entry records the parameters
# and the kind of method (coroutine or not) that the override assumes
OVERRIDDEN_METHODS = {
    "setup_peer_connection": (("self", "pc", "client_id"), False),
    "handle_request": (("self", "ws", "message"), True),
    "_add_ice_candidate": (("self", "data"), False),
    "close": (("self",), True),
    "_count_unauth_live": (("self",), False),
    "_send_with_backpressure": (
        ("self", "channel", "frame", "limit", "sctp"),
        True,
    ),
}
# what publish_form passes to bitbang's constructor and then sets on it
ADAPTER_KEYWORDS = ("program_name", "server", "pin", "ephemeral")
ADAPTER_ATTRIBUTES = ("peers", "ws_target")
# the keys that FormtuistBitBang reads from each peer bitbang registers
PEER_KEYS = (
    publisher.PEER_CONNECTION_KEY,
    publisher.PEER_AUTHENTICATED_KEY,
    publisher.PEER_RELAY_GATE_KEY,
)
DUNDER_PREFIX = "__"


class FailingDataChannel(FakeDataChannel):
    """Data channel whose send always fails."""

    def send(self, data: bytes) -> None:
        """Refuse every frame."""
        raise RuntimeError("send failed")


class ScriptEndedError(Exception):
    """Signal that a scripted signaling socket has no messages left."""


class ScriptedSignaling(FakeSignaling):
    """Signaling socket that delivers a fixed list of messages, then ends."""

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        """Queue the messages that the device will receive in order."""
        super().__init__()
        self.incoming = [json.dumps(message) for message in messages]

    async def recv(self) -> str:
        """Deliver the next message, or end the script when none remain."""
        if not self.incoming:
            raise ScriptEndedError
        return self.incoming.pop(0)


def request_message(client_id: str) -> dict[str, Any]:
    """Build a connection request as the signaling server forwards it."""
    return {
        "type": "request",
        "client_id": client_id,
        "browser_ip": BROWSER_IP,
    }


def candidate_message(client_id: str, candidate: str) -> dict[str, Any]:
    """Build an ICE candidate message as the signaling server forwards it."""
    return {
        "type": "candidate",
        "client_id": client_id,
        "candidate": {
            "candidate": candidate,
            "sdpMid": MEDIA_ID,
            "sdpMLineIndex": 0,
        },
    }


def make_adapter(**tuning: Any) -> publisher.FormtuistBitBang:
    """Build an adapter with no persisted identity and no network."""
    adapter = publisher.FormtuistBitBang(
        make_app(),
        program_name=PROGRAM_NAME,
        ephemeral=True,
        debug=False,
    )
    for name, value in tuning.items():
        setattr(adapter, name, value)
    return adapter


async def wait_until_gone(adapter: Any, client_id: str) -> None:
    """Wait for the background reaper to forget a client."""
    async with asyncio.timeout(WAIT_SECONDS):
        while client_id in adapter.peers:
            await asyncio.sleep(FAST_INTERVAL)


def frame_flags(frame: bytes) -> int:
    """Return the SWSP flags carried by one frame."""
    _, flags, _ = struct.unpack_from(FRAME_HEADER, frame)
    return int(flags)


def run_quietly(scenario: Callable[[], Coroutine[Any, Any, None]]) -> str:
    """Run a scenario and return the console output bitbang produced."""
    # bitbang prints every request, so capture it here to keep the suite
    # silent even when pytest runs with output capturing turned off
    buffer = io.StringIO()
    with (
        contextlib.redirect_stdout(buffer),
        contextlib.redirect_stderr(buffer),
    ):
        asyncio.run(scenario())
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def offline_bitbang(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run bitbang on fake WebRTC with a throwaway home directory."""
    monkeypatch.setattr(
        bitbang_adapter, "RTCPeerConnection", FakePeerConnection
    )
    for variable in HOME_VARIABLES:
        monkeypatch.setenv(variable, str(tmp_path))


class TestBitbangContract:
    """Fail loudly if a bitbang release changes the internals we rely on."""

    @pytest.mark.parametrize("name", sorted(OVERRIDDEN_METHODS))
    def test_overridden_method_keeps_its_signature(self, name: str) -> None:
        """Bitbang and the override still agree on each method's shape."""
        parameters, is_coroutine = OVERRIDDEN_METHODS[name]
        theirs = getattr(bitbang_adapter.BitBangWSGI, name, None)
        ours = getattr(publisher.FormtuistBitBang, name)
        assert theirs is not None
        for method in (theirs, ours):
            assert tuple(inspect.signature(method).parameters) == parameters
            assert inspect.iscoroutinefunction(method) is is_coroutine

    def test_every_override_is_covered_by_the_contract(self) -> None:
        """A new override of a bitbang method must be listed above."""
        overridden = {
            name
            for name in vars(publisher.FormtuistBitBang)
            if not name.startswith(DUNDER_PREFIX)
            and hasattr(bitbang_adapter.BitBangWSGI, name)
        }
        assert overridden == set(OVERRIDDEN_METHODS)

    def test_constructor_accepts_what_publish_passes(self) -> None:
        """Bitbang still takes the keywords and sets the attributes we use."""
        keywords = inspect.signature(
            bitbang_adapter.BitBangWSGI.__init__
        ).parameters
        assert set(ADAPTER_KEYWORDS) <= set(keywords)
        adapter = make_adapter()
        for attribute in ADAPTER_ATTRIBUTES:
            assert hasattr(adapter, attribute)

    def test_registered_peer_has_the_keys_formtuist_reads(self) -> None:
        """Every peer bitbang registers carries the keys the adapter reads."""

        async def scenario() -> None:
            adapter = make_adapter()
            await offer(adapter, CLIENT)
            assert set(PEER_KEYS) <= set(adapter.peers[CLIENT])
            await adapter.close()

        run_quietly(scenario)


class TestStuckSessionAdmission:
    """Admission must count stuck sessions, not in-flight handshakes."""

    def test_burst_beyond_the_stock_cap_is_admitted(self) -> None:
        """Every client in a simultaneous burst gets a connection."""

        async def scenario() -> None:
            adapter = make_adapter()
            admitted = 0
            for index in range(BURST_CLIENTS):
                ok, ws = await offer(adapter, f"{CLIENT}{index}")
                admitted += int(ok and bool(ws.sent))
            assert admitted == BURST_CLIENTS
            assert adapter._count_unauth_live() == 0
            await adapter.close()

        assert REJECTION_MARKER not in run_quietly(scenario)

    def test_stuck_sessions_still_consume_admission_slots(self) -> None:
        """The brute-force cap still engages for genuinely stuck peers."""

        async def scenario() -> None:
            adapter = make_adapter(stuck_after=0.0)
            for index in range(CAPACITY):
                ok, _ = await offer(adapter, f"{CLIENT}{index}")
                assert ok
            assert adapter._count_unauth_live() == CAPACITY
            refused, _ = await offer(adapter, LATE_CLIENT)
            assert refused is False
            await adapter.close()

        assert REJECTION_MARKER in run_quietly(scenario)

    def test_authenticated_sessions_are_not_counted(self) -> None:
        """Completing the handshake frees the admission slot."""

        async def scenario() -> None:
            adapter = make_adapter(stuck_after=0.0)
            await offer(adapter, CLIENT)
            assert adapter._count_unauth_live() == 1
            assert authenticate(adapter, CLIENT)
            assert adapter._count_unauth_live() == 0
            await adapter.close()

        run_quietly(scenario)

    @pytest.mark.parametrize("state", [CLOSED, FAILED])
    def test_ended_connections_are_not_counted(self, state: str) -> None:
        """A peer whose connection has ended must not hold a slot."""

        async def scenario() -> None:
            adapter = make_adapter(stuck_after=0.0)
            await offer(adapter, CLIENT)
            adapter.peers[CLIENT]["pc"].connectionState = state
            assert adapter._count_unauth_live() == 0
            await adapter.close()

        run_quietly(scenario)

    def test_peer_without_a_connection_is_not_counted(self) -> None:
        """A peer whose connection vanished must not hold a slot."""

        async def scenario() -> None:
            adapter = make_adapter(stuck_after=0.0)
            await offer(adapter, CLIENT)
            adapter.peers[CLIENT]["pc"] = None
            assert adapter._count_unauth_live() == 0
            await adapter.close()

        run_quietly(scenario)

    def test_visitor_at_the_pin_prompt_counts_once_stuck(self) -> None:
        """A connected but unauthenticated peer still counts once stuck."""

        async def scenario() -> None:
            adapter = make_adapter(stuck_after=0.0)
            await offer(adapter, CLIENT)
            adapter.peers[CLIENT]["pc"].connectionState = CONNECTED
            assert adapter._count_unauth_live() == 1
            await adapter.close()

        run_quietly(scenario)

    def test_request_without_a_client_id_is_tolerated(self) -> None:
        """A malformed request must not raise inside the adapter."""

        async def scenario() -> None:
            adapter = make_adapter()
            await adapter.handle_request(
                FakeSignaling(), {"browser_ip": BROWSER_IP}
            )
            await adapter.close()

        assert BROKEN_MARKER not in run_quietly(scenario)


class TestPeerAges:
    """Each registered peer carries exactly one age stamp."""

    def test_admitted_peer_is_stamped(self) -> None:
        """A peer is stamped when bitbang registers it."""

        async def scenario() -> None:
            adapter = make_adapter()
            await offer(adapter, CLIENT)
            assert set(adapter._first_seen) == {CLIENT}
            await adapter.close()

        run_quietly(scenario)

    def test_refused_request_leaves_no_stamp(self) -> None:
        """A refused request never registers a peer, so it is not stamped."""

        async def scenario() -> None:
            adapter = make_adapter(stuck_after=0.0)
            for index in range(CAPACITY):
                await offer(adapter, f"{CLIENT}{index}")
            refused, _ = await offer(adapter, LATE_CLIENT)
            assert refused is False
            assert LATE_CLIENT not in adapter._first_seen
            await adapter.close()

        run_quietly(scenario)

    def test_unstamped_peer_is_aged_from_first_sight(self) -> None:
        """A peer registered without a stamp is stamped when first seen."""

        async def scenario() -> None:
            adapter = make_adapter(stuck_after=0.0)
            adapter.peers[CLIENT] = {
                "pc": FakePeerConnection(),
                "authenticated": False,
            }
            assert adapter._count_unauth_live() == 1
            assert CLIENT in adapter._first_seen
            await adapter.close()

        run_quietly(scenario)

    def test_reaping_prunes_orphaned_stamps(self) -> None:
        """A stamp with no matching peer is discarded by the reaper."""

        async def scenario() -> None:
            adapter = make_adapter()
            adapter._first_seen[ORPHAN_CLIENT] = 0.0
            assert await adapter.reap_once() == 0
            assert adapter._first_seen == {}
            await adapter.close()

        run_quietly(scenario)

    def test_reconnect_replaces_the_previous_peer(self) -> None:
        """A reconnecting client closes its old peer and gets a fresh one."""

        async def scenario() -> None:
            adapter = make_adapter()
            await offer(adapter, CLIENT)
            old_pc = adapter.peers[CLIENT]["pc"]
            ok, _ = await offer(adapter, CLIENT)
            assert ok
            assert old_pc.closed
            assert adapter.peers[CLIENT]["pc"] is not old_pc
            assert set(adapter._first_seen) == {CLIENT}
            await adapter.close()

        run_quietly(scenario)


class TestPeerReaping:
    """Unservable peers must be reclaimed so a slot is never lost forever."""

    def test_stale_handshakes_are_reaped(self) -> None:
        """A handshake that never connected is closed and forgotten."""

        async def scenario() -> None:
            adapter = make_adapter(stale_after=0.0)
            await offer(adapter, CLIENT)
            pc = adapter.peers[CLIENT]["pc"]
            assert await adapter.reap_once() == 1
            assert adapter.reaped_sessions == 1
            assert CLIENT not in adapter.peers
            assert CLIENT not in adapter._first_seen
            assert pc.closed
            await adapter.close()

        run_quietly(scenario)

    def test_fresh_handshakes_are_not_reaped(self) -> None:
        """A handshake younger than the stale threshold is left alone."""

        async def scenario() -> None:
            adapter = make_adapter(stale_after=NEVER)
            await offer(adapter, CLIENT)
            assert await adapter.reap_once() == 0
            assert CLIENT in adapter.peers
            await adapter.close()

        run_quietly(scenario)

    @pytest.mark.parametrize("state", [CLOSED, FAILED])
    @pytest.mark.parametrize("authenticated", [False, True])
    def test_ended_connections_are_reaped_at_once(
        self, state: str, authenticated: bool
    ) -> None:
        """A peer whose connection ended is reclaimed without a wait."""

        async def scenario() -> None:
            adapter = make_adapter(stale_after=NEVER)
            await offer(adapter, CLIENT)
            if authenticated:
                assert authenticate(adapter, CLIENT)
            adapter.peers[CLIENT]["pc"].connectionState = state
            assert await adapter.reap_once() == 1
            assert CLIENT not in adapter.peers
            await adapter.close()

        run_quietly(scenario)

    def test_live_authenticated_sessions_are_never_reaped(self) -> None:
        """A live, authenticated session must survive the reaper."""

        async def scenario() -> None:
            adapter = make_adapter(stuck_after=0.0, stale_after=0.0)
            await offer(adapter, CLIENT)
            assert authenticate(adapter, CLIENT)
            assert await adapter.reap_once() == 0
            assert CLIENT in adapter.peers
            await adapter.close()

        run_quietly(scenario)

    def test_visitor_at_the_pin_prompt_is_not_reaped(self) -> None:
        """A connected visitor who is still typing a PIN keeps the session."""

        async def scenario() -> None:
            adapter = make_adapter(stale_after=0.0)
            await offer(adapter, CLIENT)
            pc = adapter.peers[CLIENT]["pc"]
            pc.connectionState = CONNECTED
            assert await adapter.reap_once() == 0
            assert adapter.peers[CLIENT]["pc"] is pc
            assert not pc.closed
            await adapter.close()

        run_quietly(scenario)

    def test_reaper_spares_a_peer_that_reconnected_mid_sweep(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fresh peer registered during a sweep must not be closed by it."""

        async def scenario() -> None:
            adapter = make_adapter(stale_after=0.0)
            await offer(adapter, CLIENT)
            await offer(adapter, OTHER_CLIENT)
            stale_peer = adapter.peers[OTHER_CLIENT]
            first_pc = adapter.peers[CLIENT]["pc"]
            close_first = first_pc.close

            async def close_while_neighbour_reconnects() -> None:
                await close_first()
                await offer(adapter, OTHER_CLIENT)

            monkeypatch.setattr(
                first_pc, "close", close_while_neighbour_reconnects
            )
            assert await adapter.reap_once() == 1
            fresh_peer = adapter.peers[OTHER_CLIENT]
            assert fresh_peer is not stale_peer
            assert not fresh_peer["pc"].closed
            await adapter.close()

        run_quietly(scenario)

    def test_reconnect_during_a_sweep_is_still_admitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A reconnect that races the reaper must still receive an offer."""

        async def scenario() -> None:
            adapter = make_adapter()
            await offer(adapter, CLIENT)
            old_pc = adapter.peers[CLIENT]["pc"]
            old_pc.connectionState = FAILED
            close_old = old_pc.close

            async def close_during_a_sweep() -> None:
                await adapter.reap_once()
                await close_old()

            monkeypatch.setattr(old_pc, "close", close_during_a_sweep)
            ok, ws = await offer(adapter, CLIENT)
            assert ok
            assert ws.sent
            assert adapter.peers[CLIENT]["pc"] is not old_pc
            await adapter.close()

        assert BROKEN_MARKER not in run_quietly(scenario)

    def test_reaper_loop_sweeps_without_being_called(self) -> None:
        """The background reaper reclaims peers on its own schedule."""

        async def scenario() -> None:
            adapter = make_adapter(
                stale_after=0.0, reap_interval=FAST_INTERVAL
            )
            await offer(adapter, CLIENT)
            await wait_until_gone(adapter, CLIENT)
            assert adapter.reaped_sessions == 1
            await adapter.close()

        run_quietly(scenario)

    def test_reaper_is_restarted_after_finishing(self) -> None:
        """A finished reaper task is replaced by a fresh one."""

        async def scenario() -> None:
            adapter = make_adapter()

            async def finished() -> None:
                return None

            adapter._reaper = asyncio.ensure_future(finished())
            await asyncio.sleep(0)
            assert adapter._reaper.done()
            adapter._ensure_reaper()
            assert adapter._reaper is not None
            assert not adapter._reaper.done()
            await adapter.close()

        run_quietly(scenario)

    def test_dropping_a_replaced_peer_is_refused(self) -> None:
        """Only the peer that is still registered can be dropped."""

        async def scenario() -> None:
            adapter = make_adapter()
            await offer(adapter, CLIENT)
            old_peer = adapter.peers[CLIENT]
            await offer(adapter, CLIENT)
            assert await adapter._drop_peer(CLIENT, old_peer) is False
            assert CLIENT in adapter.peers
            assert not adapter.peers[CLIENT]["pc"].closed
            await adapter.close()

        run_quietly(scenario)

    def test_dropping_a_peer_cancels_its_relay_gate(self) -> None:
        """The pending relay-gate timer is cancelled with the peer."""

        async def scenario() -> None:
            adapter = make_adapter()
            await offer(adapter, CLIENT)
            gate = asyncio.ensure_future(asyncio.sleep(LONG_DEADLINE))
            peer = adapter.peers[CLIENT]
            peer["relay_gate_task"] = gate
            assert await adapter._drop_peer(CLIENT, peer)
            await asyncio.sleep(0)
            assert gate.cancelled()
            assert CLIENT not in adapter.peers
            await adapter.close()

        run_quietly(scenario)

    def test_dropping_a_peer_without_a_connection_is_safe(self) -> None:
        """A peer whose connection is gone can still be dropped."""

        async def scenario() -> None:
            adapter = make_adapter()
            await offer(adapter, CLIENT)
            peer = adapter.peers[CLIENT]
            peer["pc"] = None
            assert await adapter._drop_peer(CLIENT, peer)
            assert CLIENT not in adapter.peers
            await adapter.close()

        run_quietly(scenario)

    def test_a_failing_close_does_not_block_the_drop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A connection that refuses to close is still forgotten."""

        async def scenario() -> None:
            adapter = make_adapter()
            await offer(adapter, CLIENT)
            peer = adapter.peers[CLIENT]

            async def explode() -> None:
                raise RuntimeError("close failed")

            monkeypatch.setattr(peer["pc"], "close", explode)
            assert await adapter._drop_peer(CLIENT, peer)
            assert CLIENT not in adapter.peers
            await adapter.close()

        run_quietly(scenario)


class TestCandidateHandling:
    """One browser's bad candidate must never take the publisher offline."""

    def test_valid_candidate_reaches_the_connection(self) -> None:
        """A well-formed candidate is still handed to the peer connection."""

        async def scenario() -> None:
            adapter = make_adapter()
            await offer(adapter, CLIENT)
            adapter._add_ice_candidate(
                candidate_message(CLIENT, HOST_CANDIDATE)
            )
            await asyncio.sleep(0)
            assert len(adapter.peers[CLIENT]["pc"].candidates) == 1
            await adapter.close()

        run_quietly(scenario)

    @pytest.mark.parametrize(
        "message",
        [
            candidate_message(CLIENT, END_OF_CANDIDATES),
            candidate_message(CLIENT, GARBLED_CANDIDATE),
            {"type": "candidate", "client_id": CLIENT},
            {
                "type": "candidate",
                "client_id": CLIENT,
                "candidate": GARBLED_CANDIDATE,
            },
        ],
    )
    def test_unusable_candidates_are_ignored(
        self, message: dict[str, Any]
    ) -> None:
        """An empty, garbled, or missing candidate is dropped quietly."""

        async def scenario() -> None:
            adapter = make_adapter()
            await offer(adapter, CLIENT)
            adapter._add_ice_candidate(message)
            await asyncio.sleep(0)
            assert adapter.peers[CLIENT]["pc"].candidates == []
            await adapter.close()

        run_quietly(scenario)

    def test_bad_candidate_does_not_end_the_signaling_loop(self) -> None:
        """Requests after an end-of-candidates marker are still served."""

        async def scenario() -> None:
            adapter = make_adapter()
            signaling = ScriptedSignaling(
                [
                    request_message(CLIENT),
                    candidate_message(CLIENT, END_OF_CANDIDATES),
                    request_message(OTHER_CLIENT),
                ]
            )
            with pytest.raises(ScriptEndedError):
                await adapter._message_loop(signaling)
            offered = [
                json.loads(sent)["client_id"] for sent in signaling.sent
            ]
            assert offered == [CLIENT, OTHER_CLIENT]
            await adapter.close()

        run_quietly(scenario)


class TestAdapterClose:
    """Closing the adapter must end the reaper and every peer."""

    def test_close_stops_the_reaper_and_forgets_every_peer(self) -> None:
        """Every peer is closed and the reaper task is cancelled."""

        async def scenario() -> None:
            adapter = make_adapter()
            await offer(adapter, CLIENT)
            await offer(adapter, OTHER_CLIENT)
            pcs = [peer["pc"] for peer in adapter.peers.values()]
            reaper = adapter._reaper
            assert reaper is not None
            await adapter.close()
            assert reaper.cancelled()
            assert adapter._reaper is None
            assert adapter.peers == {}
            assert adapter._first_seen == {}
            assert all(pc.closed for pc in pcs)

        run_quietly(scenario)

    def test_close_without_a_reaper_is_harmless(self) -> None:
        """An adapter that never served a request closes cleanly."""

        async def scenario() -> None:
            adapter = make_adapter()
            await adapter.close()
            assert adapter.peers == {}

        run_quietly(scenario)


class TestSendDeadline:
    """A stalled peer must fail its stream, never silently lose a frame."""

    def test_frame_is_sent_when_the_buffer_has_room(self) -> None:
        """A frame is written when the backlog is within the limit."""

        async def scenario() -> None:
            adapter = make_adapter()
            channel = FakeDataChannel()
            await adapter._send_with_backpressure(
                channel, FRAME, SMALL_LIMIT, None
            )
            assert channel.sent == [FRAME]

        run_quietly(scenario)

    def test_closed_channel_is_not_written(self) -> None:
        """Nothing is sent once the channel is closed."""

        async def scenario() -> None:
            adapter = make_adapter()
            channel = FakeDataChannel()
            channel.readyState = CLOSED
            await adapter._send_with_backpressure(
                channel, FRAME, SMALL_LIMIT, None
            )
            assert channel.sent == []

        run_quietly(scenario)

    def test_frame_is_sent_once_the_backlog_drains(self) -> None:
        """A send waits out a temporary backlog and then delivers."""

        async def scenario() -> None:
            adapter = make_adapter(send_deadline=LONG_DEADLINE)
            channel = FakeDataChannel()
            channel.bufferedAmount = HUGE_BACKLOG
            send = asyncio.create_task(
                adapter._send_with_backpressure(
                    channel, FRAME, SMALL_LIMIT, None
                )
            )
            await asyncio.sleep(FAST_INTERVAL)
            assert not send.done()
            channel.bufferedAmount = 0
            await asyncio.wait_for(send, WAIT_SECONDS)
            assert channel.sent == [FRAME]

        run_quietly(scenario)

    def test_channel_closing_while_waiting_ends_quietly(self) -> None:
        """A peer that goes away mid-wait releases the handler."""

        async def scenario() -> None:
            adapter = make_adapter(send_deadline=LONG_DEADLINE)
            channel = FakeDataChannel()
            channel.bufferedAmount = HUGE_BACKLOG
            send = asyncio.create_task(
                adapter._send_with_backpressure(
                    channel, FRAME, SMALL_LIMIT, None
                )
            )
            await asyncio.sleep(FAST_INTERVAL)
            channel.readyState = CLOSED
            await asyncio.wait_for(send, WAIT_SECONDS)
            assert channel.sent == []

        run_quietly(scenario)

    def test_stalled_peer_raises_instead_of_dropping_the_frame(self) -> None:
        """A permanently full buffer fails loudly at the deadline."""

        async def scenario() -> None:
            adapter = make_adapter(send_deadline=0.0)
            channel = FakeDataChannel()
            channel.bufferedAmount = HUGE_BACKLOG
            with pytest.raises(publisher.SendStalledError):
                await adapter._send_with_backpressure(
                    channel, FRAME, SMALL_LIMIT, None
                )
            assert channel.sent == []

        run_quietly(scenario)

    def test_sctp_flight_size_counts_toward_the_backlog(self) -> None:
        """In-flight SCTP bytes are part of the backpressure check."""

        async def scenario() -> None:
            adapter = make_adapter(send_deadline=0.0)
            channel = FakeDataChannel()
            transport = SimpleNamespace(_flight_size=HUGE_BACKLOG)
            with pytest.raises(publisher.SendStalledError):
                await adapter._send_with_backpressure(
                    channel, FRAME, SMALL_LIMIT, transport
                )
            assert channel.sent == []

        run_quietly(scenario)

    def test_send_errors_reach_bitbang(self) -> None:
        """A failing send is reported, not swallowed mid-stream."""

        async def scenario() -> None:
            adapter = make_adapter()
            with pytest.raises(RuntimeError):
                await adapter._send_with_backpressure(
                    FailingDataChannel(), FRAME, SMALL_LIMIT, None
                )

        run_quietly(scenario)

    def test_stalled_stream_ends_with_an_error_response(self) -> None:
        """Bitbang answers a stalled stream with a complete 500 response."""

        async def scenario() -> None:
            adapter = make_adapter(send_deadline=0.0)
            channel = FakeDataChannel()
            channel.bufferedAmount = HUGE_BACKLOG
            await adapter._handle_swsp_request(
                channel, STREAM_ID, GET_ROOT, None, client_id=None
            )
            flags = [frame_flags(frame) for frame in channel.sent]
            assert flags == [
                bitbang_adapter.FLAG_SYN,
                bitbang_adapter.FLAG_DAT,
                bitbang_adapter.FLAG_FIN,
            ]
            head = json.loads(channel.sent[0][FRAME_HEADER_SIZE:])
            assert head["status"] == SERVER_ERROR

        run_quietly(scenario)
