# Bitbang admission control when publishing forms

Formtuist's `publish` command reaches visitors through
[bitbang](https://pypi.org/project/bitbang/), a peer-to-peer WebRTC tunnel. The
tunnel admits only a small number of *unauthenticated* peers at once, which is a
problem when a whole class opens one published link at the same moment. This
page records the diagnosis, the fix in `src/formtuist/publisher.py`, and how to
test both.

## The symptom

Some or all visitors never reach the form. Their browser shows bitbang's
`Loading...` indefinitely, while the publisher's terminal prints:

```text
Rejecting connection from ...: too many pending sessions (10)
```

A PIN is not required to trigger this. Restarting the publisher appears to fix
it, and it gets worse the longer a session runs.

## The cause

Two behaviours in bitbang combine into a permanent lockout.

1. **The ten-slot budget counts connection *setups*, not visitors.** Bitbang
   registers a peer when the signaling `offer` arrives and marks it
   authenticated only when the SWSP `connect` message arrives over the data
   channel. That window spans the whole ICE/DTLS/SCTP handshake, and at least
   `RELAY_GRACE` (8 seconds) whenever the TURN relay is used. So
   `MAX_UNAUTH_PEERS = 10` really means ten concurrent handshakes, and a burst
   of thirty visitors exceeds it immediately, even when every one of them would
   authenticate on the next message.

2. **Peers that never authenticate are never reclaimed.** They are removed only
   on reconnect or adapter close, so ten abandoned loads pin every slot for the
   life of the process. Every later visitor is then refused from the first
   second, which is why nobody sees the form at all, and why the failure looks
   permanent rather than like a capacity limit.

The refusal is also **silent**: the adapter returns without answering the
offer, so the browser is given nothing to report and simply waits.

## What is not the cause

Textual-serve is not involved. Driving it directly, with no bitbang in the path,
thirty concurrent sessions are served and reclaimed:

| Measurement | Result |
| --- | --- |
| Concurrent sessions | 30/30 served |
| Page assets (`/`, `textual.js`, `xterm.css`) | all `200` |
| App processes while connected | 56 live (about two per session) |
| App processes after disconnect | 0 |

## The fix

`FormtuistBitBang` subclasses `BitBangWSGI` inside `src/formtuist/publisher.py`.
Bitbang itself is not modified, forked, or monkeypatched at runtime beyond the
test doubles used by the suite.

- `_count_unauth_live` counts only sessions that have stayed unauthenticated for
  `stuck_after` seconds (45 by default), so visitors who are merely mid-handshake
  no longer consume a slot. Genuinely stuck sessions are still capped, so the
  brute-force defence is preserved.
- A background reaper closes and forgets peers that are dead or have lingered
  unauthenticated for `stale_after` seconds (120 by default), so an abandoned
  load cannot hold a slot forever.
- `_send_with_backpressure` gains a deadline, so a stalled peer can no longer
  pin a request handler indefinitely.

## How to test

### 1. The load test

`scripts/bitbang_loadtest.py` drives bitbang's real `handle_request` path with
in-process doubles, so it needs no browser, no network, and no signaling server:

```bash
uv run scripts/bitbang_loadtest.py --clients 30
```

It compares stock `BitBangWSGI` against `FormtuistBitBang` and exits non-zero if
the expected difference is not observed. The expected output is:

```text
scenario                                 baseline          fixed
burst                                 20 rejected     0 rejected
burst+auth                            20 rejected     0 rejected
abandoned age=0.08s                   10 rejected    10 rejected
abandoned age=0.30s                   10 rejected     0 rejected
```

`burst` shows that stock bitbang refuses twenty of thirty simultaneous setups.
`abandoned age=0.08s` shows the defence still engaging once sessions are stuck.
`abandoned age=0.30s` shows the reaped case, where stock refuses the late
arrivals forever and the fix admits all of them.

### 2. The unit tests

```bash
uv run pytest tests/test_bitbang_admission.py
```

Twenty-three tests cover stuck-session accounting, peer reaping, and the send
deadline. They reuse the load test's doubles and redirect `HOME` so no identity
is written to `~/.bitbang`.

### 3. A manual smoke test

```bash
uv run formtuist publish examples/minimal.json
```

Open the printed URL once from a second device. Before the fix, repeating that
open/close cycle about ten times eventually refuses every new visitor; after the
fix, a refused visitor is the exception rather than the rule.

## Until this is merged

Two operational mitigations reduce the blast radius of stock bitbang:

- restart `formtuist publish` immediately before a session, because an
  abandoned load never frees its slot;
- ask visitors to use campus Wi-Fi rather than cellular, because a direct path
  handshakes in one to two seconds and rarely touches the cap, while a relayed
  path holds a slot for at least eight seconds.

For a class-sized group, serving the form behind a Cloudflare Tunnel with an
Access policy avoids the peer-to-peer admission limit entirely, at the cost of
running the `cloudflared` binary.

## Upstream

Both behaviours are worth reporting to
[richlegrand/bitbang-python](https://github.com/richlegrand/bitbang-python),
whose Go counterpart (`cmd/bitbang/serve.go`) carries the same
`maxUnauthSessions = 10` constant, with the comment "A single human needs
exactly one".
