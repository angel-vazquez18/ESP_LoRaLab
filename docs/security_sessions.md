# Session keys and protected-frame boundaries (#44)

This document maps the selected v2 security contract to the current run APIs.
The firmware now composes owned private key setup, [session-key retirement](session_key_lifecycle.md)
and [protected DATA/replay/retry acceptance](protected_replay.md). Available selected
radios advertise node GCM support; #63 implements fresh shared-host provisioning,
allowlisted setup records and independent persistence guards. See
[protected host sessions](protected_host_sessions.md) for current behavior and checks. [Local crypto measurement](crypto_benchmark.md) is implemented in #53.
#48 provides the isolated
[authenticated-frame primitive](frame_crypto.md). Public vectors are conformance
data, never evidence that installed firmware implements security.

## Provision one fresh key pair per run

After both identities, boots, capabilities and idle ownership are verified, the
host generates independent 16-byte OS-CSPRNG keys K_A and K_B in RAM. K_A protects
all frames sourced by A, and K_B all frames sourced by B, including DATA, ACK and
ECHO. Session ID, role or nonce alone does not separate two sources using the
same key. Normal runs must not load the fixed public conformance keys.

| Call | Key assignment | What may be retained |
| --- | --- | --- |
| `session.open` to A | `tx_key_hex = K_A`, `rx_key_hex = K_B` | Session/run IDs, device/boot/peer IDs, profile, random key-set ID and provisioning booleans |
| `session.open` to B | `tx_key_hex = K_B`, `rx_key_hex = K_A` | The same safe setup facts, never key bytes or key-derived fingerprints |
| `config.set`, `run.prepare`, `run.arm`, `run.start` | No keys in arguments | Requested/applied settings, revision, source specification and timing budget |
| `run.stop`, `session.close` | No replacement keys | Reason, bounded cleanup outcome and idle/closed observations |

Open binds the existing envelope run ID and peer device/boot. The keys travel
only on the trusted locally owned USB control links. If either provisioning
reply is lost or fails, stop/close both attempted sessions, retire the pair and
use fresh keys for a new run. Never continue with one provisioned peer or infer
successful setup from a timeout. Provisioning must not put keys into firmware
source, NVS, profiles, artifact storage, SQLite or exports.

## Secret-bearing fields and persistence boundaries

The exact secret command paths are `session.open.args.tx_key_hex` and
`session.open.args.rx_key_hex`. Both are 32 hexadecimal characters when protected;
both are null for `none`. Invalid values are still sensitive input. Do not include
them in validation errors, exception strings, request logging or crash reports.

The production provisioning path must construct an explicit safe setup record
**before** any callback or persistence. A generic JSON dump followed by later
masking is too late. Redacted setup records are evidence, not replayable setup
commands. A random `key_set_id` identifies the ephemeral setup without deriving
anything from either key.

| Boundary | Implemented behavior |
| --- | --- |
| `NodeSession.request` validation | Protected setup errors omit supplied values and input-bearing exception context |
| Setup callbacks | Receive allowlisted setup facts/results before any recording, never private command snapshots |
| Radio/transfer traces and SQLite records | Reject structured and serialized secret-bearing metadata before persistence |
| Run snapshots/history/export | Retain only the public security profile, independent key-set ID, setup facts and observed-stage assessment |
| API validation | Reject accidentally supplied secrets without echoing the request input |
| Node replies/events/errors | Return readiness, IDs and static errors; never input keys |
| Firmware session/duplicate/serial buffers | Retire private source handles and wipe parser/input buffers on cleanup |

Firmware retirement/input erasure is implemented in #52 and shared-host guards
in #63. The private host owner is retired immediately after provisioning or any
partial setup failure. Never persist `ValidationError.errors()` input/context or
a raw provisioning request. Physical acceptance remains separate under #67.

## Nonce, header and sequence ownership

Every new protected frame uses AES-128-GCM with a 12-byte nonce and full 16-byte
tag. Nonce is exactly `BE64(session_id) || BE32(frame_seq)`. All 40 transmitted
header bytes are AAD, including type, flags, roles, content, session, sequence,
message/fragment lengths, reference and reserved bytes. The header is visible
but authenticated; the body is ciphertext. Maximum protected body is 199 bytes.
A protected ACK has no plaintext body and is 56 bytes including its tag.

Each source has one monotonic sequence space shared by its DATA/ACK/ECHO, starting
at 1. Reserve needed original sequences before beginning bounded work. Never
wrap to zero or restart a counter independently of its keys. The final uint32
value may identify a final new frame; another new frame then requires a fresh
session/key pair. Retrying its retained bytes does not allocate a new sequence
or invoke encryption again. New ACKs always need a fresh responder sequence.
An encryption error retires the session rather than reusing its nonce for
changed data. Profile mismatch rejects; clearing the protected flag cannot
switch a protected session to plaintext.

The algorithm details follow [NIST SP 800-38D](https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-38d.pdf).
The independent test oracle is [Cryptography AESGCM](https://cryptography.io/en/stable/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM),
locked as a development dependency. The pinned ESP-IDF v6.0.2 checkout contains Mbed TLS 4.1.0 / TF-PSA-Crypto
1.1.0; the frame primitive uses its public PSA AEAD interface, not private legacy
GCM headers.
See the [ESP-IDF PSA migration guidance](https://docs.espressif.com/projects/esp-idf/en/v6.0/esp32s3/migration-guides/release-6.x/6.0/security.html).
A passing Python vector alone never qualifies the firmware cipher.

## Retry versus replay: receive decisions

Validate bounded framing/session/roles/profile, authenticate the exact header
and ciphertext/tag, then consult replay state before message insertion. Failed
authentication releases no plaintext and changes no replay state. The 128-packet
window is peer/session scoped across every protected frame type. A new unseen
sequence within the window can arrive out of order. Commit replay acceptance
only after applicable metadata checks and successful frame acceptance; a
resource/insertion failure must not poison a legitimate later retry.

| Situation | Decision and permitted effects |
| --- | --- |
| First valid DATA | Insert once, commit acceptance, optionally schedule an ACK |
| Identical authenticated DATA in the 16-entry accepted-frame hash cache, ACK mode enabled and inside the retry horizon | `retry_duplicate`; no insertion/delivery; may generate a fresh referenced ACK |
| Changed header/ciphertext/tag or wrong source key | Authentication failure; no plaintext, insertion, ACK or window change |
| Already-seen frame without ACK mode, outside cache/horizon, or older than the window | `replay`; no insertion/delivery/ACK |
| New valid ACK | Verify replay freshness and exact outstanding reference; finish only that original; never ACK an ACK |
| Replayed ACK | Reject; no deadline extension or sender completion |
| New valid ECHO request/reply | Validate the single-fragment known-data body/reference; use fresh source sequence; accept once |

An attacker’s identical retransmission within the declared retry exception is
indistinguishable from a legitimate retry. Both have zero new delivery. SEC-03
therefore uses ACKs disabled. Protected execution now uses the session owner's
128-frame window and 16-entry accepted-hash cache before trusted insertion/re-ACK.
`rf_ack` continues to serve unprotected runs; its structural checks alone do not
supply authentication or cryptographic replay protection.

## Retirement and restart

- Successful finite work may retain exact ciphertext for the declared drain/
  retry horizon; it cannot re-arm the completed run with old keys. Close after
  collecting summaries and independently verified artifacts.
- Cancellation or failure stops RF/DMA and incomplete message work, then closes
  the session and retires keys/replay/cache state. A restart needs fresh keys.
- Lease expiry, disconnect, reset or shutdown invalidates the session. No automatic
  reconnect/resume, counter recovery or NVS key recovery is permitted.
- Firmware explicitly zeroizes secret and temporary buffers before release. The
  host wipes mutable buffers and drops private references on every exit; Python
  and OS memory behavior does not promise complete erasure of immutable copies.
  Host process memory and the USB bench remain trusted parts of the design.

## Walkthroughs and reproducible review

A normal protected DATA from A uses K_A, the session ID, sequence 1 and the full
header as AAD; B verifies the tag before accepting it. A lost ACK causes the
exact same DATA bytes to be transmitted again. B classifies the eligible duplicate
and emits a new ACK under K_B with its next sequence, without a second delivery.
With ACKs disabled, that repeated DATA is replay, not an ACK exception. Cancel
stops both nodes and closes before another fresh setup. Exhaustion never wraps;
a new session/key pair is needed before another newly protected frame.

`contracts/v2/security_vectors.json` includes public DATA in both directions,
a protected empty-body ACK, ECHO request/reply, maximum 199-byte payload at the
final sequence, and an exact-byte retry example. Existing conformance bytes stay
unchanged. The tests check encryption/decryption independently, exact header
fields and all 40 AAD bytes, ciphertext/tag mutation, wrong nonce/source key,
ACK body/tag overhead and the final sequence/capacity boundary.

```sh
uv run --project testbed pytest testbed/tests/test_security_vectors.py testbed/tests/test_session_secrets.py -q
make check
```

Expect all focused checks without skips and secret sentinels absent from serialized
rejection/trace evidence. #48/#52 cover the cipher and firmware lifecycle; #60
covers protected transport/replay. #63 adds successful paired runs, actual saved
file/export scans, partial setup, cancellation and fresh reconnect checks. See
[the 31-case focused command](protected_host_sessions.md#reproduce-software-checks).
Physical qualification under #67 remains pending.
