# V2 known-data preparation

> Historical document. The November 1 physical-only decision supersedes the
> simulator workflows and commands below; those implementations were removed.
> See [current status](status.md) and [host usage](../testbed/README.md).

October 26, 2026. Host preparation and the baseline virtual v2 execution path
are implemented; physical v2 experiment execution is not. See `v2_execution.md`
for actual simulated runs and campaigns. A preview opens no serial ports, changes no node settings,
allocates no run/session and creates no hardware evidence.

## Use

In the Experiments workspace select IF-02 and use **Plan and run a simulation**.
Choose message count/size, direction, SF, bandwidth, security, reliability and
maximum duration, then calculate. Download the result to retain its normalized
plan and hashes. Editing a setting clears the prior preview. Results from an
older request are ignored if settings change while it is pending.

The UI fixes 915 MHz, CR 4/5, 14 dBm, 160 useful bytes per fragment and seed 743.
The API/CLI accept the other validated v2 settings in a plan JSON file. A
stop-and-wait request defaults to two retries; explicitly requesting zero or one
retry is supported. ACK-disabled plans must request zero retries.

With the backend running at its default port:

```sh
uv run --project testbed lora-testbed preview-v2
uv run --project testbed lora-testbed preview-v2 --plan contracts/v2/known_data_example.json
```

HTTP interfaces:

- `POST /api/experiments/v2/known-data/preview`: validate a plan and calculate it.
  An empty object selects the unprotected IF-02 bring-up defaults.
- `GET /api/protocol/v2/known-data`: plan and staged RF event schemas, scope,
  execution availability and event-schema SHA-256.
- `GET /api/protocol/v2`: unchanged diagnostic schema and digest used by the
  installed firmware and `NodeSession`.

The v2 Start button and campaign path now execute actual virtual-node byte
processing. Explicit legacy controls retain v1 behavior. Hardware RF start
remains blocked, including after a calculated preview fits its duration.

## Inputs and validation

`KnownDataPlan` contains `radio`, `link` and `spec`. Defaults are materialized
when normalizing. The spec is limited to IF-02/known-data preparation, with
explicit nulls for inapplicable audio/artifact/reference fields. The initial
bring-up default is security `none`; `aes128_gcm` can be calculated without
claiming firmware cryptography exists.

Validation covers the 902–928 MHz profile in 1 kHz steps; SF7–12; supported
bandwidth/coding/power ranges; fixed explicit-header/CRC/IQ/sync settings;
16–215 useful fragment bytes (at most 199 protected); ACK/retry consistency;
1–10000 messages; 1–65536 useful bytes; and 1–3600 second finite duration.
Simulation-only loss/duplicate parameters and unknown fields are rejected.
Constants retain their JSON types: integer 1 is not boolean true, and floating
point 5156.0 is not the integer sync word.

The capability list is a requirement, not a report from a device. Actual board
limits, applied LDRO/settings, buffer availability and firmware readiness must be
checked by the virtual run adapter and, later, qualified hardware. Fault and audio budgets are zero in this
known-data preparation slice. Required packet events remain enabled.

## Payload and duration calculations

Expected bytes use the contract's SHA-256 block recipe and the public
cross-language conformance vector. The result includes a first-message digest;
successive messages have distinct IDs. A plan hash covers the full normalized
input, including defaults and direction. It is not a firmware or result hash.

Frame capacity includes the 40-byte header and optional 16-byte GCM tag. Fragment
count and exact final-fragment size are computed without shortening messages.
The airtime model uses integer quarter-symbol arithmetic, the explicit-header
SF7–12 domain and the automatic 16 ms LDRO threshold. These are requested-profile
predictions until applied hardware settings and timing are qualified.

The expanded bound includes every permitted attempt, the full ACK timeout for
each attempt when enabled, guards between successive attempts, the contract's
provisional processing allowance and bounded drain. Processing allows 10000 us
per message plus 10000 us per maximum attempt. ACK timeout is 100000 us plus ACK
airtime; drain is max(2000000 us, ACK timeout plus guard). Reassembly budget is
the per-message expanded attempt/wait/guard/processing bound plus 2000000 us.
Nominal calculation uses one attempt and a successful ACK turnaround/airtime.
Neither calculation predicts loss, RSSI/SNR, goodput or measured CPU performance.

The preview retains the requested count and maximum duration. It requires
ceil(bound_us/1000) plus 1000 ms headroom, including at the duration boundary.
If that requirement does not fit, it returns an explicit blocker and a recommendation of at
least max(120000 ms, ceil(bound_us/1000) + 1000 ms). A recommendation beyond one
hour becomes null with a required linked-split flag. No setting is automatically
applied, clamped or reduced.

## Staged event schema

`rf_events_v2.py` types `run.state`, `run.prepared`, `tx.attempt`, `rx.frame`,
`rx.accepted` and `message.result`, including identities, units and bounded
fields. A completed transmission requires ordered command/completion timestamps.
A delivered message requires a complete hash, timestamps and zero missing parts.
Zero frame/message sequences and the all-zero session identity are rejected.
For this staged profile, frame types are the strings `data`, `ack`,
`echo_request`, `echo_reply`; attempt status is `completed`/`failed` and message
status is `delivered`/`failed`.

The virtual execution profile now includes rejections, missing-index parts,
summaries, asynchronous outcomes and typed baseline command arguments/results.
It is not an adopted firmware schema. Security/audio/timing families still need
implementation, followed later by matching firmware adoption.
The diagnostic decoder continues to reject RF event names. Do not
advertise capabilities or bypass its compatibility check to connect a richer
build. Adopt the expanded wire profile, digest and firmware together.

Generate the checked-in schemas with:

```sh
uv run --project testbed python scripts/generate_contract.py
```

This preserves the diagnostic schema/digest and generates
`contracts/v2/known_data.schema.json`, `known_data_events.schema.json` and
`execution.schema.json`.
No reference firmware image or hardware run is generated.

## Verification and next work

Independent numerical vectors are PL120/SF7 = 199936 us, PL216/SF7 = 343296 us
and PL216/SF12 = 7872512 us at BW125 kHz, CR4/5 and preamble eight. The default
unprotected preview has 104-byte DATA frames and a 26895600 us expanded run
bound. The protected equivalent has 120-byte frames and a 28943600 us bound.
These are calculated examples, not laboratory measurements.

Tests cover the reference bytes/hash, these airtime vectors, fragment boundaries,
protected capacity, ACK/retry accounting, insufficient duration and linked
splits, invalid settings, event evidence validation, diagnostic compatibility
and absence of preview side effects. Additional execution checks are documented
in `v2_execution.md` and `implementation_status.md`.

The shared adapter, baseline typed messages and bounded virtual lifecycle are
implemented. Next complete each dedicated simulated procedure matrix and its
feature families, starting with IF-01/IF-02/IF-03. Hardware integration follows
through a matching serial-backed adapter. Keep simulation-ready and
hardware-validated status separate in `experiment_implementation_checklist.md`.
