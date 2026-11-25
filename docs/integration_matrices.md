# Shared integration procedure runner

The testbed can preview the complete IF-01, IF-02 and IF-03 case plans and run
the combinations listed below. Each row keeps its group, variant, repetition,
readiness, assessment and references to its original child evidence.

| Procedure | Executable software coverage | Remaining coverage |
| --- | --- | --- |
| IF-01 Serial interface | Main-control USB claim, keepalive, release and reclaim, plus actual invalid argument, unknown command and unavailable command replies. C3 framing and parser recovery. One connected role is enough. | Settings integrity, version/schema rejection, reply perturbation, competing control, lease expiry and UART-specific cases. |
| IF-02 Known-data exchange | Four payload lengths (1, 64, 159 and 160 bytes), both roles, seeded repetitions, and deliberate peer mismatch with a verified restored configuration. | Full bench repetitions and qualification of the physical timing and delivery conditions. |
| IF-03 Campaign persistence | Baseline, pause/resume, cancellation, configuration failure, selected reruns, concurrent-start rejection and verified exports. | Refresh/navigation across a live case and process restart in active and paused states. |

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

A peer mismatch control verifies applied settings on both roles and stops at
configuration before session setup or radio arming. Its follow-up restores
matching settings and verifies bytes. Campaign exports verify the complete
linked graph, including both file transfers per completed radio child.

The procedure CSV/ZIP contains the case ledger and each child's evidence link.
Fetch the saved radio/campaign export for the child's complete raw evidence.
The [matrix compiler](../testbed/src/lora_testbed/integration_matrices.py)
defines the planned coverage. The
[executor](../testbed/src/lora_testbed/integration_execution.py) uses the
existing serial, radio, campaign and evidence services.

## Software checks

```sh
uv run --project testbed pytest testbed/tests/test_serial_framing_matrix.py testbed/tests/test_integration_matrices.py testbed/tests/test_physical_campaign_execution.py testbed/tests/test_campaign_reruns_evidence.py -q
make check
```

The isolated C/radio fixture verifies the shortened IF-02 matrix, the one-node
serial replies, whole-matrix stop, and six campaign groups. These results preserve
the physical qualification status for review on the bench.
