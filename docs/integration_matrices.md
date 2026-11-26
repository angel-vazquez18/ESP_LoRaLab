# Shared integration procedure runner

The testbed can preview the complete IF-01, IF-02 and IF-03 case plans and run
the combinations listed below. Each row keeps its group, variant, repetition,
readiness, assessment and references to its original child evidence.

| Procedure | Executable software coverage | Remaining coverage |
| --- | --- | --- |
| IF-01 Serial interface | Claim, keepalive, release and reclaim on the firmware's selected transport. C2 command errors and configuration preservation, C3 framing and parser recovery, C4 compatibility rejection, C5 reply perturbation, conflict and stale-boot rejection, and C6 ownership, lease expiry and health watchdog. One connected role is enough. | Physical qualification on native USB and UART. |
| IF-02 Known-data exchange | Four payload lengths (1, 64, 159 and 160 bytes), both roles, seeded repetitions, and deliberate peer mismatch with a verified restored configuration. | Full bench repetitions and qualification of the physical timing and delivery conditions. |
| IF-03 Campaign persistence | Baseline, pause/resume, cancellation, configuration failure, selected reruns, concurrent-start rejection and verified exports. | Refresh/navigation across a live case and the supervised operator restart matrix. |

The full IF-02 plan has 24 positive case groups with 100 messages each and six
peer mismatch controls. The full IF-03 plan has 25 case groups. Each baseline
campaign groups its finite messages into three repetitions in both directions.
A linked message gets its own session. Keep that timing boundary when comparing
measurements with a continuous-message workload.

## Preview, run and review

In **Experiments**, select a procedure that offers a matrix. Choose one case
group or all groups, pick a quick check or the procedure defaults, and
preview the cases. The panel lists readiness and blockers before enabling
**Run ready cases**. The start request binds that preview's plan hash.
A changed plan requires a fresh preview. **Stop matrix** targets its active
run and waits for cleanup. Use **Inspect cases** to reopen the saved ledger
with case evidence and an evidence ZIP. This view uses the same procedure
store as the CLI. Neither path awards physical qualification.

From the CLI, save a JSON request with the desired scope. For example, a short
IF-02 subset is:

```json
{
  "catalog_id": "IF-02",
  "groups": ["C1", "C2", "C3"],
  "repetitions": 1,
  "messages_per_case": 2
}
```

```sh
uv run --project testbed lora-testbed integration-matrix matrix.json --preview
uv run --project testbed lora-testbed integration-matrix matrix.json
uv run --project testbed lora-testbed procedure-status RUN_ID
```

Omit the shortened settings to preview the declared full plan. The preview
reports blockers by case. Use an explicit start on the testbed with the required
nodes. The executor maintains the bench owner across the selected cases and
keeps the device, boot and connection bindings. A stopped, interrupted or failed
child retains its reference and cleanup record. Unavailable cases remain visible
as blocked. The shared stop command waits for the active case or campaign to
finish cleanup before returning.

IF-01 C2 runs four variants per role with three default repetitions.
The configuration variant requires compatible radio firmware. It reads
applied settings, submits one fixed invalid frequency, then verifies
the firmware returned `INVALID_ARGUMENT` and the radio, link and revision
readbacks are unchanged. A node that has yet to apply settings reports
null radio and link readbacks. The case compares those values and the
revision as its baseline. Nodes without radio support can still run the
other three C2 variants.

IF-01 C3 runs nine variants, each repeated three times by default per
selected role. It checks representative board splits, concatenation, CRLF,
the inclusive 4,096-byte line limit, discard and recovery at 4,097 bytes,
duplicate keys, invalid UTF-8, malformed JSON and every split of a valid
host-decoder fixture. The decoder fixture re-encodes an observed status
reply. Each board variant correlates fresh status replies and saves exact
write sizes and SHA-256 hashes, expected and observed firmware counter
deltas, and idle recovery. Missing rejection counters are inconclusive.
The case stops if device ownership or connection changes. USB hardware
qualification and the UART path remain separate.

IF-01 C4 uses a fresh hello from the connected role as the baseline.
A separate one-shot hello fixture changes the advertised wire version,
contract version, or schema digest. The ordinary handshake must reject
that precise incompatibility, close the fixture port and send only hello.
The three variants each have three default repetitions per role. The
case records the observed identity and the altered fixture separately.

IF-01 C5 uses a bounded host fixture on a single memory probe. It can
drop one reply and require a timeout, delay delivery until after one
retry, or drop the first reply and accept the retry response. Each case
requires one independently observed completion. Retried writes must
have identical bytes and the fixture records their hashes. The
conflict variant changes bytes under the same cached command identity
and requires COMMAND_CONFLICT. To exercise stale-boot rejection, connect
the same node, reset it and reconnect it to this running testbed. The
testbed retains the previous observed boot on that role. The case targets
that boot with a bounded diagnostic and requires STALE_BOOT, zero new
diagnostic results and fresh idle status on the current boot. The three
default probes use the observed boot pair. Repeat the reset and reconnect
sequence when a separate physical boot transition is required.

IF-01 C6 checks a competing client and an expiring lease three times
per selected role. The live owner refreshes its lease before the competing
claim. The firmware must return BUSY and leave the original role usable.
For expiry the testbed pauses keepalive on that connection, records the
firmware lease deadline and waits for actual unowned idle health. The
expired client must receive NOT_OWNER. A fresh claim on the same link
must restore idle status. Interrupted probes attempt to restore control.
The health-silence variant preserves the original health events in the
raw ledger and withholds them from the connection's freshness tracker.
The watchdog must report stale health after three seconds and disconnect
after the five-second unresponsive threshold. The testbed then opens a
fresh connection on the same port and verifies the same device and boot
are idle. Subsequent cases use the new connection binding. The initial
binding and each change remain in the saved run.

A peer mismatch control verifies applied settings on both roles and stops at
configuration before session setup or radio arming. Its follow-up restores
matching settings and verifies bytes. Campaign exports verify the complete
linked graph, including both file transfers per completed radio child.

When a new host opens a saved active or paused campaign, it records the
last persisted campaign stage and case ID as the restart checkpoint.
An active child is interrupted, completed children are retained, and
unstarted cases are skipped. A radio trace fingerprint taken at startup
identifies the bytes recovered from disk. Use the saved campaign bundle to
verify those bytes and check the separate delivery and cleanup records.
The campaign cannot resume and a new run must pass fresh connection and
ownership preflight. The native subprocess test covers active transmission
and a settled pause following a completed child. The supervised IF-03 C6
and OPS-01 C3 schedules and physical acceptance remain open.

The procedure CSV/ZIP contains the case ledger and each child's evidence link.
Fetch the saved radio/campaign export for the child's complete raw evidence.
The [matrix compiler](../testbed/src/lora_testbed/integration_matrices.py)
defines the planned coverage. The
[executor](../testbed/src/lora_testbed/integration_execution.py) uses the
existing serial, radio, campaign and evidence services.

## Serial transports for IF-01

The default firmware uses native USB Serial/JTAG. The UART build uses
UART0 at 115200 8N1 with GPIO43 as TX and GPIO44 as RX. From the repository
root with ESP-IDF active, build the UART image separately:

```sh
idf.py -C firmware/lora_node -B /tmp/loralab-uart-build \
  -D SDKCONFIG=/tmp/loralab-uart-sdkconfig \
  -D 'SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.uart.defaults' build
```

Select the verified board settings separately if the test needs radio or
audio capability. Power the board through USB-C. Use a 3.3 V logic UART
adapter. Join grounds and cross TX and RX. On the standard Heltec V4
pin layout, J2 position 6 is GPIO43/TX and J2 position 5 is GPIO44/RX.

Connect the adapter's serial device in Setup, then choose UART in the
IF-01 matrix. The CLI takes `"transports": ["uart"]` in its matrix request.
Preview compares each selected transport with that role's hello record.
To qualify both transports, keep their runs and evidence separate.
On a bare UART, loss of communication is bounded by the existing lease
and host watchdog.

## Software checks

```sh
uv run --project testbed pytest testbed/tests/test_serial_framing_matrix.py testbed/tests/test_integration_matrices.py testbed/tests/test_physical_campaign_execution.py testbed/tests/test_campaign_reruns_evidence.py -q
make check
```

The isolated C/radio fixture verifies the shortened IF-02 matrix, the one-node
serial replies, whole-matrix stop, and six campaign groups. These results preserve
the physical qualification status for review on the bench.
