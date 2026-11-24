# Authenticated frame primitive (#48)

`firmware/lora_node/main/security/frame_crypto` implements bounded AES-128-GCM
through the public PSA AEAD API supplied by the pinned ESP-IDF v6.0.2 crypto
tree. The API imports a caller-supplied 16-byte key into a volatile, non-exportable
PSA handle, seals a complete protected frame, verifies/decrypts a frame and
explicitly destroys that handle. It contains no fixed/public keys.

The cipher follows [session security](security_sessions.md): nonce is the
12 contiguous header bytes at offsets 8–19, AAD is the complete 40-byte header,
and the full 16-byte tag follows ciphertext. A body is at most 199 bytes and a
complete frame at most 255. Protected empty-body ACKs carry a tag. DATA, ACK and
ECHO framing/role/reserved/length bounds reject before cipher use. Message-level
metadata validation remains the execution owner’s responsibility.

## Output and lifetime rules

`rf_crypto_create(key, key_bytes, &owner)` requires an empty owner and exactly
16 input bytes. The caller owns the input buffer; the primitive retains only
the opaque PSA key handle. Attributes permit AES-128 GCM encrypt/decrypt, with
volatile lifetime and no export permission. A failed creation leaves no owner.

`rf_crypto_seal` takes an already authorized protected header and useful body,
returns exact header/ciphertext/tag bytes, and leaves caller output unchanged
on failure. It does not allocate or reset sequences: the session owner must
reserve a fresh source sequence for every newly protected frame. Retries transmit
the retained result without another cipher invocation.

`rf_crypto_open` decrypts into a private 199-byte temporary. It copies to caller
output only after successful tag verification and exact plaintext length.
Failure leaves output unchanged and reports zero written bytes. All temporary
frame/plaintext buffers are zeroized on every cipher exit. Authentication
failure is distinct from invalid framing, arguments, unavailable backend or
allocation failure. A rejected frame does not poison the next valid operation.

`rf_crypto_destroy(&owner)` destroys the PSA key, zeroizes/frees the context and
clears the caller owner. Empty destruction is safe. A backend cleanup failure
preserves ownership so the enclosing session can quarantine the context and
retry explicit cleanup instead of losing an unconfirmed live handle.

## Pinned dependency and native check

`security/crypto_dependency.json` records Mbed TLS 4.1.0 / TF-PSA-Crypto 1.1.0
from IDF’s submodule commit `6cc42afad309e861f4c07e6f106e2ab14a9cb8e5`.
The upstream [source](https://github.com/espressif/mbedtls/tree/6cc42afad309e861f4c07e6f106e2ab14a9cb8e5/tf-psa-crypto)
is used under its Apache-2.0 option. No third-party source is copied into this
module. Firmware uses the normal IDF component and configured PSA drivers.

The native fixture compiles that exact clean crypto source with CMake and links
the same frame-cipher implementation. `IDF_PATH` can select a non-default source
location; otherwise it checks `~/.espressif/v6.0.2/esp-idf`. A missing/wrong/modified
dependency fails with instructions rather than skipping or substituting another
cipher. Native checks require CMake and a C compiler; macOS uses the existing
Xcode `xcrun` compiler/SDK selection. All output stays in ignored
`firmware/lora_node/.cache/native-crypto`. The fixture does not fetch dependencies
or access physical ports.

`testbed/tests/native/psa_crypto_config.h` selects the pinned software AES/GCM
implementation, SHA-256, normal host entropy/DRBG and pthread locking. It excludes
unrelated asymmetric algorithms and persistent key storage. Upstream fatal
warnings are disabled only for that vendor build: the reduced profile may emit
an unreachable-code warning in generic key-derivation code. Project source
still compiles with `-Wall -Wextra -Werror`. This native profile does not validate
ESP hardware acceleration, target stack usage or timing.

## Reproduce the checks

From repository root, with the pinned SDK available:

```sh
uv run --project testbed pytest testbed/tests/test_frame_crypto_native.py -q
make check
idf.py -C firmware/lora_node build
```

The focused check must run without skips. Expected results: exact independent
public vectors for both source keys, protected DATA/ACK/ECHO and the maximum
199-byte body/final sequence; changing each header/ciphertext/tag byte or source
key rejects without modifying caller plaintext; a valid frame still works after
each failure; empty ACK, short/oversized buffers, malformed keys and repeated
create/destroy hold their bounds. Two hundred successive imports/destructions
exercise key-slot cleanup. Read tests beside the public API for exact assertions.

The first known-answer test was observed failing at the unimplemented API, then
passing against the actual PSA implementation. Independent Cryptography vectors
from #44 remain the byte oracle, not a replacement native cipher.

## Integration and hardware still pending

The main image now composes the primitive through #52’s private session-key
owner. Owned firmware setup can load keys and enforce nonce lifetime, while
`security_gcm` remains false and protected RF/host work is blocked. #60 must
integrate replay/transport before application insertion, and #63 must provision/
redact keys through the shared host. #53 adds local measurements. See
[session lifetime](session_key_lifecycle.md).
No protected operator run or physical security result is claimed by this slice.

Later physical acceptance under #67 must identify both boards/firmware profiles,
verify actual protected DATA/ACK exchange and once-only delivery, exercise bad
authentication/old sessions and demonstrate close, lease-loss, reset, exhaustion
and failed-provisioning cleanup. Export only safe setup facts and observed
counts/timestamps, never session key material.

The separate [local benchmark](crypto_benchmark.md) measures checked one-shot PSA
API calls using only public diagnostic vectors. It does not time this wrapper's
framing/copy logic or enable protected RF operation.
