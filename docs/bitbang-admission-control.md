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
- A background reaper, run every `reap_interval` seconds (10 by default),
  forgets two kinds of peer: any peer whose connection has ended (`closed` or
  `failed`, which aiortc never leaves), and any unauthenticated handshake that
  has not connected within `stale_after` seconds (60 by default). An abandoned
  load therefore cannot hold a slot forever, and `self.peers` no longer grows
  with every visitor who ever connected.
- `_send_with_backpressure` stops waiting as soon as the channel closes, and
  raises `SendStalledError` when a live peer has not drained for
  `send_deadline` seconds (15 by default), so a stalled peer can no longer pin a
  request handler indefinitely.

### Design notes

A few choices are deliberate and are covered by regression tests.

- **A connected visitor at the PIN prompt is never reaped.** A peer whose
  connection is up but who has not authenticated is a person typing a PIN.
  Closing it would strand that person, so it only counts toward the admission
  cap once stuck. When the tab closes, aiortc moves the peer to `closed` or
  `failed`, and the reaper reclaims it then.
- **A stalled send raises instead of skipping the frame.** SWSP runs over a
  reliable, ordered channel with no gap detection, so a silently skipped frame
  corrupts the response body. If the skipped frame is the final `FIN`, the
  browser waits forever. Raising lets bitbang finish the stream with a complete
  500 response. Send errors propagate to bitbang for the same reason.
- **Peers are dropped by identity, not by client id.** The reaper awaits each
  `close()`, and a reconnecting client can register a fresh peer under the same
  id during that await. A drop therefore only removes the exact peer it judged
  unservable. `handle_request` also retires a reconnecting client's old peer
  itself, because bitbang's own cleanup deletes by key after an await and would
  raise `KeyError` if the reaper got there first. Bitbang swallows that error,
  so the visitor would receive no offer.
- **Each peer carries exactly one age stamp.** The stamp is written in
  `setup_peer_connection`, which bitbang calls in the same synchronous step
  that registers the peer. A refused request is therefore never stamped, and
  the reaper prunes any stamp left without a peer.
- **A bad ICE candidate is ignored instead of taking the publisher offline.**
  Bitbang parses each candidate a browser trickles in inside its signaling
  loop, with no error handling. A candidate that aiortc cannot parse, such as
  the empty end-of-candidates marker the WebRTC specification allows, raised
  out of that loop. The publisher then dropped off the signaling server and
  waited three seconds before registering again. Tabs that were already
  connected kept working, because their traffic is peer to peer, but anyone who
  opened or refreshed the page in that window saw "Device not found".
  `FormtuistBitBang` now drops such a candidate, which affects only the browser
  that sent it.
- **Bitbang is capped below 0.2, and a contract test guards its internals.**
  `FormtuistBitBang` overrides methods that bitbang treats as private, which a
  release may change without notice. `pyproject.toml` therefore requires
  `bitbang>=0.1.55,<0.2`. A minor release, which may break things before 1.0,
  needs a deliberate upgrade. A patch release can still change private methods,
  so `TestBitbangContract` in `tests/test_bitbang_admission.py` records the
  signature of every overridden method. It also checks the constructor keywords
  and attributes that `publish_form` uses, and the peer keys the adapter reads,
  and fails loudly if any of them change. Versions 0.1.55 and 0.1.56 both pass.

The refusal that remains for genuinely stuck sessions is still silent, because
bitbang's signaling protocol has no message that tells the browser it was
turned away. The fix makes that refusal rare; it cannot make it visible.

## How to test

### 1. The load test

`scripts/bitbang_loadtest.py` drives bitbang's real `handle_request` path with
in-process doubles, so it needs no browser, no network, and no signaling server:

```bash
uv run scripts/bitbang_loadtest.py --clients 30
```

It compares stock `BitBangWSGI` against `FormtuistBitBang` and exits non-zero if
the expected difference is not observed. Stock bitbang only refuses a burst that
is larger than its cap of ten, so a run with ten or fewer clients checks only
that the fix refuses nobody. The expected output is:

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

The same scenarios also run in the test suite, in
`tests/test_bitbang_loadtest.py`, for a class of thirty and for a group of five
that stock bitbang never refuses. Those tests assert every row of the table
above and both outcomes of the verdict, so `uv run task all` fails if the fix
stops removing the lockout. The stuck scenario never reaps, so its reap
threshold sits far beyond its probe age; a slow machine therefore cannot reap
the abandoned sessions part-way through and turn the result flaky.

### 2. The unit tests

```bash
uv run pytest tests/test_bitbang_admission.py
```

Fifty-four tests cover the bitbang contract, stuck-session accounting, age
stamps, peer reaping (including the reconnect races), adapter shutdown, the send
deadline, and candidate handling. One test drives bitbang's real WSGI send loop
to show that a stalled stream ends with a complete 500 response. Another drives
bitbang's real signaling loop to show that an empty end-of-candidates marker no
longer stops the publisher from answering the requests that follow. The tests
reuse the load test's doubles. Every adapter uses an ephemeral identity, so
nothing is written to `~/.bitbang`. As a second safeguard, the tests point both
`HOME` and `USERPROFILE` at a temporary directory, since Windows resolves `~`
through `USERPROFILE`. Bitbang's console output is captured, so the suite stays
silent even under `pytest -s`.

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
