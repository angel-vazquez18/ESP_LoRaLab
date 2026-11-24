# Owned session keys and nonce lifetime (#52)

The firmware now accepts an owned `session.open` with `aes128_gcm` and two
distinct canonical lowercase 16-byte hex keys. It binds that setup to the current
client, logical role, run/session ID and peer device/boot through the existing
execution lifecycle. The private `security/session_crypto` owner imports separate
TX/RX volatile PSA handles. Keys and counters are created/retired together.

The main image now uses this owner in the [protected radio/replay path](protected_replay.md)
from #60. It advertises node GCM support when the selected radio is available;
`security_ready` separately reports loaded usable keys. Shared host provisioning
now uses #63's fresh ephemeral owner, allowlisted setup callbacks and independent
persistence guards; see [protected host sessions](protected_host_sessions.md). Local public-vector measurements are implemented in #53.
No new firmware was flashed for these software checks.

## Source ownership and sequence reservation

The key owner binds a nonzero session ID and local A/B role. TX headers must name
that local source/session; RX headers must name the peer and reverse direction.
The two source keys must differ. Receiving a peer frame does not consume the
local TX counter. No key or counter setter is exposed after creation.

`rf_secure_reserve` reserves a nonzero count from the source’s monotonic uint32
space. It checks the whole addition in uint64 before changing state. Failure
reports zero first sequence; wrap is impossible. Seal accepts only a reserved
sequence greater than the previous attempted seal, and burns it before calling
the cipher. Unused/skipped reservations and failed attempts never return to the
pool. Once the final sequence is used, neither another reservation nor encrypting
that same header succeeds. Exact retries use retained ciphertext without sealing
again. DATA and ACK now share the appropriate source owner; future ECHO must do the same.

The owner validates source/session binding before cipher use. It preserves the
frame primitive’s private plaintext scratch and unchanged output on failure.
Authentication failure does not consume TX sequences or invalidate a healthy
receive key; backend failures disable further access pending cleanup.

Freshness of caller-provided key bytes is a trusted-host precondition. The node
checks format, distinct source keys and binding, prevents active replacement and
nonce reuse within the owner, and never restores retired handles/counters. It
does not prove OS-CSPRNG freshness or compare every key across reboots. #63
generates a fresh independent pair per source/run and never reloads historical
material. Public fixed-key tests are isolated conformance fixtures.

## Control and cleanup

Key import occurs only when the owned, validated mutation has a reserved encoded
correlated reply. JSON/reply allocation failure or backpressure cannot leave
unreported successful key setup. Decode buffers are wiped after PSA import; the
execution plan retains no borrowed provisioning-JSON pointer or raw key bytes.

Close, stop, lease expiry, disconnect and controller destruction disable key
access and destroy both handles, wipe/free the private owner and clear readiness.
Partial two-source import failure destroys the first handle before returning. A
failed backend destruction retains a disabled owner for explicit cleanup rather
than dropping an unconfirmed handle. No cleanup path re-enables that owner.

Retiring keys also evicts successful key-bearing setup replies from the duplicate
cache. Client sequence fences stay in place: replaying the retired setup command
cannot return an old success or import old material again. Active sessions already
lock role changes. New work needs a new owned setup with fresh caller keys.

## Secret-bearing input memory

`protocol/secure_json` installs aligned, sized cJSON allocation hooks at startup,
before JSON allocation. Every owned JSON block is wiped before its underlying
free, including failed parses, duplicate-name rejection and allocation-failure
cleanup inside cJSON. This closes the path that command-handler-only wiping
cannot reach. The allocator adds one aligned size header per allocation; target
heap/latency qualification remains separate. Never reconfigure cJSON hooks while
objects are live; code must use cJSON’s matching release API for its buffers.

Raw serial input is wiped after each record, oversize rejection, disconnect and
destruction. Lease loss also wipes unfinished input and discards its remaining
bytes through LF. A complete record arriving at the lease boundary still gets
normal ownership checking and correlation before its buffer is wiped. Parser
cleanup and record framing remain independent of secret-field spelling.

The native allocator observer saw two unwiped secret strings at the duplicate-
name rejection boundary before the fix and zero afterward. A separate partial-
record test observed 462 bytes retained after lease loss before that fix and zero
afterward. Tests observe real deallocation/health/framing boundaries, not private
key getters. No secret value is returned in replies, events, errors or health.

## Vocabulary migration and host guard

The selected baseline already specifies protected setup. The typed execution
subset now represents its `none`/null or `aes128_gcm`/distinct-key variants, with
key fields marked write-only and omitted from model repr. Invalid session error
text still omits input. `NodeSession.request` now permits protected setup only
with matching GCM capability and replaces private setup snapshots with allowlisted
facts before callbacks. Missing capability rejects before recording or writing.

The #52 execution digest was
`88ddc6ba2422af593c0ba91ad1350f9f4ba411a3f037fae09b31ee5c4fc1e775`
(previous `880c3e59e3c569c96f30603bfcbd132373a67050df2fc80d1b80aa9949718949`).
Rebuild matching host/firmware stacks for RF; do not relabel older evidence or
bypass exact compatibility. Main-control, diagnostic, artifact and audio digests
are unchanged. #63 subsequently adds explicit accepted-ACK evidence and a new
execution digest; use [the current migration](protected_host_sessions.md#matching-profile-migration)
when rebuilding the protected operator stack.

## Review and checks

Read `security/session_crypto.c` for private source/counter lifetime, then
`radio/rf_execution.c` for owned setup/retirement and `control/node_control.c` for
readiness/cache/input cleanup. `protocol/secure_json.c` owns parser-memory
release. Typed vocabulary and the private setup boundary are in `run_protocol_v2.py`
and `nodes.py`. Native firmware and cipher checks share the actual pinned PSA
builder in `testbed/tests/native_crypto.py`.

```sh
uv run --project testbed pytest testbed/tests/test_secure_sessions_native.py testbed/tests/test_session_crypto_native.py testbed/tests/test_session_secrets.py -q
make check
idf.py -C firmware/lora_node build
```

Expect 19 focused passes without skips: opposite source keys/counters, final-
sequence exhaustion, burned failed attempt, real close/stop/lease/disconnect/
reset, stale setup rejection, bad keys/ownership/backpressure, 160 allocation-
failure positions, parser and partial-input erasure, and cleanup when the second
PSA import cannot obtain a slot. The missing-capability host guard must reject before any trace.

Physical #67 still needs actual provisioned boards, stable identity/boot evidence,
lease/disconnect/reset/exhaustion recovery and safe captured records after the
remaining security integration. Native key-slot limits and software crypto do
not establish ESP memory headroom, acceleration or timing.
