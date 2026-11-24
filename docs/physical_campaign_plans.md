# Physical campaign plans (#81)

A saved plan records intent before any case runs: exact settings, repetitions,
directions, source seeds, order, node requirements and linked batches. Creating,
previewing or loading a plan opens no ports and starts no work. Campaign execution
is the separate #87 issue; dashboard controls follow #88. Capability workflows
are not full CDR procedure qualification.

## Try the documented plan

With the backend running, from repository root:

```sh
uv run --project testbed lora-testbed campaign-plan testbed/examples/local_and_radio_plan.json --preview
uv run --project testbed lora-testbed campaign-plan testbed/examples/local_and_radio_plan.json
uv run --project testbed lora-testbed campaign-plans
uv run --project testbed lora-testbed campaign-plan-result PLAN_UUID
```

The example expands three local memory probes and six directional known-data
checks: nine cases, one batch and a 600-second planning reserve. Offline preview
works; disconnected nodes produce explicit readiness blockers. This reserve is
not a measured runtime or RF performance prediction.

HTTP uses the same backend:

- `POST /api/physical-campaigns/plans/preview`: validate and preview without saving.
- `POST /api/physical-campaigns/plans`: atomically save the complete immutable plan.
- `GET /api/physical-campaigns/plans?limit=20`: bounded summaries without raw cases.
- `GET /api/physical-campaigns/plans/{id}`: exact saved cases, settings and links,
  with the document hash checked before returning it.

The old simulator campaign routes still return 410. Historical records are kept
in their original storage; these physical plans use a separate table in the same
backend-owned SQLite database. Plans remain planned after restart, with no port
opening, automatic execution or rewriting of old interrupted/blocked cases.

## Supported selections

Each template has a unique label and one typed case. Existing production request
models validate known data, voice and crypto settings. Local selections explicitly
choose role A or B; RF requires both roles and distinct physical device identities.

| Case kind | Settings | Required nodes | Scope |
| --- | --- | --- | --- |
| `memory_probe` | role, iterations, payload bytes | 1 | Local memory capability check |
| `crypto_benchmark` | role, existing benchmark request | 1 | Local checked public-vector measurements |
| `serial_check` | role, cycles | 1 | Existing partial IF-01 diagnostic check |
| `audio` | role, capture/play/retrieve/codec/decode, file or sample count | 1 | Existing finite local audio workflow |
| `known_data` | existing radio-run request | 2 | One finite message per expanded case |
| `voice` | existing secure-voice request | 2 | Reference/microphone clip and selected comparisons |
| `procedure` | catalog ID, local/RF workload, roles and planning budget | Catalog-dependent | Full required matrix reference, explicitly blocked |

All 23 required CDR procedures can be retained as references, including currently
unavailable matrices. MEM-01 and OPS-01 preserve separate local/RF requirements.
A procedure reference is not a substitute implementation or an invented passing
case. Its operator-supplied budget is a planning reservation, not a measured or
validated matrix duration. Full-matrix implementation must supply its real
procedure bounds before execution becomes available.

Capture creates a new artifact at execution. Other audio actions require an
explicit existing artifact ID and use that file's manifest sample count; ignored
sample overrides are rejected. A voice reference requires its reference ID.
Private session keys are not accepted or saved in plans. Fresh keys belong to
the actual run, not reusable campaign settings.

## Repetitions, directions and stable links

The expansion walks repetition, template, then direction. Global `directions`
controls known-data/voice expansion; local cases and full procedure references
occur once per repetition. Normalized expanded requests contain their actual
direction. Within a known-data repetition, directions/settings retain their
selected source seed; repetition n uses `(base_seed+n-1) mod 2^32`.

Sequential order preserves that expansion. Randomized order sorts by SHA-256 of
`seed_u32_big_endian || canonical_index_u32_big_endian`; the saved algorithm is
`sha256_seed_and_canonical_index_v1`. This does not depend on a Python shuffle
implementation. The six-case seed-19 vector is `[2,0,5,4,3,1]`; seed 20 gives
`[5,2,1,3,4,0]`. Cases retain their original canonical index after shuffling.

Each saved plan has its own UUID. Case and batch UUIDs are scoped to that plan;
semantic order is reproducible across separate plans, while their identities
remain independent. Every case retains template/repetition/direction, canonical
and final index, batch ID, requirements and an initially empty child-run link.
Every batch retains parent, previous/next batch IDs and its ordered case IDs.
Later execution records link child runs by these stable case IDs; the saved plan
is not rewritten as work runs.

The normalized spec and full saved document have separate hashes. Planner source,
spec schema and selected host-source fingerprints record the interpretation used
at creation. Live readiness is a timestamped cached capability snapshot, never
permission to reuse a USB connection or proof of hardware qualification. Execution
must recheck identities, ownership, firmware/capabilities and file availability.

## Bounds and batching

Up to 64 templates and 100 repetitions may expand to at most 4,096 cases, with a
16 MiB serialized-plan bound. A batch contains at most 64 cases and 1,800 seconds
of declared reserves. Splitting happens after saved order is established; no case
is dropped. For example, 100 local 50-second checks split 36/36/28 by time. The
75-case blocked-reference fixture splits 64/11 by count. All totals and links
remain available in the parent plan.

Current capability reserves come from the existing host timeouts plus explicit
setup/cleanup allowance:

| Workload | Planning reserve |
| --- | --- |
| Memory, crypto or serial diagnostic | 50 seconds |
| Local audio | 260 seconds |
| Known data | ceiling(request timeout / 1,000) + 65 seconds |
| Secure voice | ceiling(timeout × selected 1-or-3 RF stages / 1,000) + 360 seconds |
| Unavailable full procedure reference | Operator budget, 1–1,800 seconds |

These are application planning limits, not measured execution times or guarantees
about operating-system delays. An atomic case above 30 minutes is rejected before
saving; splitting it silently would change the requested experiment. An expanded
plan above 4,096 cases is also rejected as a whole. Neither error saves a partial
plan. Later execution still needs its own bounded case/batch deadlines and cleanup.

## Reading and checking the implementation

- `campaign_plans.py`: typed selections, matched seeds, stable expansion/order,
  bounded linked batches, hashes and immutable storage.
- `host.py`: existing runner/capability readiness without starting operations.
- `app.py` / `cli.py`: shared preview, save, list and reload paths.
- `testbed/examples/local_and_radio_plan.json`: a valid offline example.

Historical `Lora_Testbed/src/lora_testbed/campaigns.py` was inspected. The
repetition/direction expansion and matched-seed policy remain useful; the current
planner uses physical request models and host timeouts. Historical artificial
packet-pacing estimates and simulator execution are not imported.

```sh
uv run --project testbed pytest testbed/tests/test_physical_campaign_plans.py -q
make check
npm --prefix testbed/frontend run format:check
```

Expected focused checks: exact save/reload/order/hash/link preservation; source
seed wrap; time/count splitting without missing cases; local node B sufficiency;
duplicate RF identities blocked; all 23 references retained; typed audio/voice/
diagnostics; invalid/private input rejected before persistence; and historical
interrupted/blocked records preserved. No fixture qualifies physical hardware.
