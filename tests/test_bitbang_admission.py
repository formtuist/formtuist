"""Tests for bitbang admission control in the formtuist publisher.

These tests drive the real ``FormtuistBitBang`` adapter through bitbang's own
``handle_request`` path, using the in-process doubles that the load-testing
tool already provides in ``scripts/bitbang_loadtest.py``. Sharing those doubles
keeps the measured behaviour and the asserted behaviour in step, and means the
suite never opens a WebRTC connection, resolves a hostname, or contacts the
bitbang signaling server.
"""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from bitbang import adapter as bitbang_adapter

from formtuist import publisher
from scripts.bitbang_loadtest import (
    BROWSER_IP,
    PROGRAM_NAME,
    FakeDataChannel,
    FakePeerConnection,
    FakeSignaling,
    authenticate,
    make_app,
    offer,
    stop_reaper,
)

# more simultaneous visitors than bitbang's own MAX_UNAUTH_PEERS allows
BURST_CLIENTS = 30
# exactly bitbang's MAX_UNAUTH_PEERS, used to show the cap still engages
CAPACITY = 10
# a buffer far larger than any backpressure limit, and one far smaller
HUGE_BACKLOG = 10**9
SMALL_LIMIT = 1024


def make_adapter(**tuning: Any) -> publisher.FormtuistBitBang:
    """Build a patched adapter with no persisted identity and no network."""
    adapter = publisher.FormtuistBitBang(
        make_app(),
        program_name=PROGRAM_NAME,
        ephemeral=True,
        debug=False,
    )
    for name, value in tuning.items():
        setattr(adapter, name, value)
    return adapter


@pytest.fixture()
def sandbox_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    """Point bitbang's identity directory at a throwaway home."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture()
def fake_webrtc(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace aiortc's peer connection with the load-test double."""
    monkeypatch.setattr(
        bitbang_adapter, "RTCPeerConnection", FakePeerConnection
    )


class TestStuckSessionAdmission:
    """Admission must count stuck sessions, not in-flight handshakes."""

    def test_burst_beyond_the_stock_cap_is_admitted(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """Every client in a simultaneous burst gets a connection."""

        async def scenario() -> None:
            adapter = make_adapter()
            admitted = 0
            for index in range(BURST_CLIENTS):
                ok, _ = await offer(adapter, f"c{index}")
                admitted += int(ok)
            assert admitted == BURST_CLIENTS
            assert len(adapter.peers) == BURST_CLIENTS
            assert adapter._count_unauth_live() == 0
            await stop_reaper(adapter)

        asyncio.run(scenario())

    def test_in_flight_handshakes_do_not_consume_a_slot(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """Fresh, unauthenticated peers are not counted as stuck."""

        async def scenario() -> None:
            adapter = make_adapter()
            for index in range(BURST_CLIENTS):
                await offer(adapter, f"f{index}")
            assert adapter._count_unauth_live() == 0
            await stop_reaper(adapter)

        asyncio.run(scenario())

    def test_stuck_sessions_still_consume_admission_slots(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """The brute-force cap still engages for genuinely stuck peers."""

        async def scenario() -> None:
            adapter = make_adapter(stuck_after=0.0)
            for index in range(CAPACITY):
                ok, _ = await offer(adapter, f"s{index}")
                assert ok
            assert adapter._count_unauth_live() == CAPACITY
            refused, _ = await offer(adapter, "one-too-many")
            assert refused is False
            await stop_reaper(adapter)

        asyncio.run(scenario())

    def test_authenticated_sessions_are_not_counted(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """Completing the handshake frees the admission slot."""

        async def scenario() -> None:
            adapter = make_adapter(stuck_after=0.0)
            await offer(adapter, "a")
            assert adapter._count_unauth_live() == 1
            assert authenticate(adapter, "a")
            assert adapter._count_unauth_live() == 0
            await stop_reaper(adapter)

        asyncio.run(scenario())

    @pytest.mark.parametrize("state", ["closed", "failed", "disconnected"])
    def test_dead_connections_are_not_counted(
        self, sandbox_home: Any, fake_webrtc: None, state: str
    ) -> None:
        """A peer in a dead state must not hold a slot."""

        async def scenario() -> None:
            adapter = make_adapter(stuck_after=0.0)
            await offer(adapter, "d")
            adapter.peers["d"]["pc"].connectionState = state
            assert adapter._count_unauth_live() == 0
            await stop_reaper(adapter)

        asyncio.run(scenario())

    def test_peer_without_a_connection_is_not_counted(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """A peer whose connection vanished must not hold a slot."""

        async def scenario() -> None:
            adapter = make_adapter(stuck_after=0.0)
            await offer(adapter, "n")
            adapter.peers["n"]["pc"] = None
            assert adapter._count_unauth_live() == 0
            await stop_reaper(adapter)

        asyncio.run(scenario())

    def test_request_without_a_client_id_is_tolerated(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """A malformed request must not raise or age anything."""

        async def scenario() -> None:
            adapter = make_adapter()
            await adapter.handle_request(
                FakeSignaling(), {"browser_ip": BROWSER_IP}
            )
            assert adapter._first_seen == {}
            await stop_reaper(adapter)

        asyncio.run(scenario())


class TestStalePeerReaping:
    """Abandoned peers must be reclaimed so a slot is never lost forever."""

    def test_stale_peers_are_swept_and_free_their_slots(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """An aged, unauthenticated peer is dropped by the reaper."""

        async def scenario() -> None:
            adapter = make_adapter(stuck_after=0.0, stale_after=0.0)
            await offer(adapter, "x")
            dropped = await adapter.reap_once()
            assert dropped == 1
            assert adapter.reaped_sessions == 1
            assert "x" not in adapter.peers
            await stop_reaper(adapter)

        asyncio.run(scenario())

    def test_dead_peers_are_swept_immediately(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """A disconnected peer is reclaimed without waiting for the TTL."""

        async def scenario() -> None:
            adapter = make_adapter(stale_after=10_000.0)
            await offer(adapter, "y")
            adapter.peers["y"]["pc"].connectionState = "disconnected"
            assert await adapter.reap_once() == 1
            assert "y" not in adapter.peers
            await stop_reaper(adapter)

        asyncio.run(scenario())

    def test_authenticated_peers_are_never_swept(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """A live, authenticated session must survive the reaper."""

        async def scenario() -> None:
            adapter = make_adapter(stuck_after=0.0, stale_after=0.0)
            await offer(adapter, "z")
            assert authenticate(adapter, "z")
            assert await adapter.reap_once() == 0
            assert "z" in adapter.peers
            await stop_reaper(adapter)

        asyncio.run(scenario())

    def test_reaper_loop_sweeps_without_being_called(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """The background reaper reclaims peers on its own schedule."""

        async def scenario() -> None:
            adapter = make_adapter(stale_after=0.0, reap_interval=0.01)
            await offer(adapter, "r")
            adapter._ensure_reaper()
            await asyncio.sleep(0.05)
            assert "r" not in adapter.peers
            await stop_reaper(adapter)

        asyncio.run(scenario())

    def test_reaper_is_restarted_after_finishing(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
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
            await stop_reaper(adapter)

        asyncio.run(scenario())

    def test_dropping_an_unknown_client_is_harmless(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """Dropping a client that is not tracked must not raise."""

        async def scenario() -> None:
            adapter = make_adapter()
            await adapter._drop_peer("missing")
            assert adapter.peers == {}

        asyncio.run(scenario())

    def test_dropping_a_peer_cancels_its_relay_gate(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """The pending relay-gate timer is cancelled with the peer."""

        async def scenario() -> None:
            adapter = make_adapter()
            await offer(adapter, "g")
            gate = asyncio.ensure_future(asyncio.sleep(30))
            adapter.peers["g"]["relay_gate_task"] = gate
            await adapter._drop_peer("g")
            await asyncio.sleep(0)
            assert gate.cancelled() or gate.cancelling()
            assert "g" not in adapter.peers

        asyncio.run(scenario())

    def test_dropping_a_peer_without_a_connection_is_safe(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """A peer whose connection is gone can still be dropped."""

        async def scenario() -> None:
            adapter = make_adapter()
            await offer(adapter, "p")
            adapter.peers["p"]["pc"] = None
            await adapter._drop_peer("p")
            assert "p" not in adapter.peers

        asyncio.run(scenario())

    def test_a_failing_close_does_not_block_the_drop(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """A connection that refuses to close is still forgotten."""

        async def scenario() -> None:
            adapter = make_adapter()
            await offer(adapter, "e")

            async def explode() -> None:
                raise RuntimeError("close failed")

            adapter.peers["e"]["pc"].close = explode
            await adapter._drop_peer("e")
            assert "e" not in adapter.peers

        asyncio.run(scenario())


class TestSendDeadline:
    """A stalled peer must never pin a request handler forever."""

    def test_closed_channel_is_not_written(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """Nothing is sent once the channel is closed."""

        async def scenario() -> None:
            adapter = make_adapter()
            channel = FakeDataChannel()
            channel.readyState = "closed"
            await adapter._send_with_backpressure(
                channel, b"x", SMALL_LIMIT, None
            )
            assert channel.sent == []

        asyncio.run(scenario())

    def test_frame_is_sent_when_the_buffer_has_room(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """A frame is written when the backlog is within the limit."""

        async def scenario() -> None:
            adapter = make_adapter()
            channel = FakeDataChannel()
            await adapter._send_with_backpressure(
                channel, b"x", SMALL_LIMIT, None
            )
            assert channel.sent == [b"x"]

        asyncio.run(scenario())

    def test_full_buffer_gives_up_at_the_deadline(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """A permanently full buffer does not block the handler."""

        async def scenario() -> None:
            adapter = make_adapter(send_deadline=0.0)
            channel = FakeDataChannel()
            channel.bufferedAmount = HUGE_BACKLOG
            await adapter._send_with_backpressure(
                channel, b"x", SMALL_LIMIT, None
            )
            assert channel.sent == []

        asyncio.run(scenario())

    def test_sctp_flight_size_counts_toward_the_backlog(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """In-flight SCTP bytes are part of the backpressure check."""

        async def scenario() -> None:
            adapter = make_adapter(send_deadline=0.0)
            channel = FakeDataChannel()
            transport = SimpleNamespace(_flight_size=HUGE_BACKLOG)
            await adapter._send_with_backpressure(
                channel, b"x", SMALL_LIMIT, transport
            )
            assert channel.sent == []

        asyncio.run(scenario())

    def test_a_send_error_is_swallowed(
        self, sandbox_home: Any, fake_webrtc: None
    ) -> None:
        """A channel that raises on send does not crash the handler."""

        async def scenario() -> None:
            adapter = make_adapter()
            channel = FakeDataChannel()

            def explode(data: bytes) -> None:
                raise RuntimeError("channel closed")

            channel.send = explode
            await adapter._send_with_backpressure(
                channel, b"x", SMALL_LIMIT, None
            )

        asyncio.run(scenario())
