# Controlled lab trials

The testbed runs a known-data control, one explicitly selected fault, and a fresh
intact control. Each child run has its own session, while the testbed keeps the
same exclusive bench owner, node connections, settings and seeded source across
the trial. It saves child IDs and per-assertion evidence links.

Both nodes must advertise the lab capability and the exact execution v6
fingerprint. The finite trial supports the first attempt or eligible arrival of
a selected fragment. It supports protected byte changes and replay, pre-insertion
drop, ACK suppression with a recovery retry, duplication and block reversal.
ACK is disabled for mutation, replay, duplication and reversal. The firmware-only
controls can express more than this single-fault trial. See
[firmware behavior and limits](lab_frame_faults.md).

## Run and inspect

In the dashboard, open **Experiments** and select PKT-02, PKT-03, SEC-02 or SEC-03.
Choose a fault and fragment index, then select **Check lab readiness**. Once the
two nodes are ready, select **Start trial**. Changing the form requires a new
preflight. Start also rechecks both connections. Stop cancels the current child,
waits for cleanup and leaves the saved record.

For the CLI, save a request such as this to a JSON file:

```json
{
  "direction": "A_TO_B",
  "security": "aes128_gcm",
  "message_bytes": 321,
  "link": {"fragment_payload_bytes": 160},
  "injection": {
    "injection_id": "85cc7ed2-05b1-45c0-841e-7420deec3909",
    "stage": "rx_before_reassembly",
    "action": "drop",
    "message_id": 1,
    "fragment_index": 1,
    "attempt_index": 1,
    "byte_offset": null,
    "xor_mask": null,
    "block_size": null
  }
}
```

```sh
uv run --project testbed lora-testbed lab-start trial.json --preview
uv run --project testbed lora-testbed lab-start trial.json
uv run --project testbed lora-testbed lab-status TRIAL_ID
```

The example expects two intact deliveries around a drop with exactly fragment 1
missing. To check recovery on an exact retry, set the link's `ack_mode` to
`stop_wait` and `max_retries` to 1 before starting. Review the selected trial's
assertions and the before/fault/after evidence bundles. Expand an assertion to
find the associated node, event name and serial event sequence. The raw records
and verified file hashes live with each linked child.

A trial can finish with a failed or inconclusive assessment. A passing result
requires both matched controls, confirmed cleanup, observed fault application
and consistent TX/RX, rejection or acceptance evidence for the selected case.
An absent arrival, CRC failure or incomplete telemetry leaves the relevant
assertion inconclusive. Node-local timestamps are compared within that node.
Restart leaves saved work interrupted and requires an explicit new start.

## Review and checks

- [`lab_trials.py`](../testbed/src/lora_testbed/lab_trials.py) owns the durable
  trial and its three child runs.
- [`radio_runs.py`](../testbed/src/lora_testbed/radio_runs.py) uses the existing
  physical adapter, key lifecycle, receiver-first arm, artifact retrieval and cleanup.
- [`fault_accounting.py`](../testbed/src/lora_testbed/fault_accounting.py) checks
  the declared target, observed wire evidence and recovery independently.
- [`LabTrials.tsx`](../testbed/frontend/src/LabTrials.tsx) uses the same API as
  the CLI and renders the stored results.

```sh
uv run --project testbed pytest testbed/tests/test_lab_trials.py -q
make check
npm --prefix testbed/frontend run format:check
```

The focused tests cover the six fault actions across real native firmware pairs,
a recovered drop with a retry, incomplete evidence, default-build gating, stop
and API preflight. The browser fixture verified a drop with a retry, the three
saved evidence links after refresh, and a hash-verified fault bundle. Complete
CDR matrices and actual over-the-air acceptance remain separate checks.
