"""All CDR experiments stay visible, including work not yet implemented."""

ROWS = [
    (
        "IF-01",
        "Integration",
        "Serial interface validation",
        "5.4",
        None,
    ),
    ("IF-02", "Integration", "Known-data link check", "1.3, 5.4", None),
    (
        "IF-03",
        "Integration",
        "Automated experiment campaign",
        "5.4",
        "Host campaign workflow available; physical RF integration pending",
    ),
    ("RF-01", "Radio", "Spreading factor sweep", "7.2", "Radio sweep runner and real nodes"),
    ("RF-02", "Radio", "Bandwidth sweep", "7.2", "Radio sweep runner and real nodes"),
    ("RF-03", "Radio", "Coding rate sweep", "7.2", "Radio sweep runner and real nodes"),
    ("RF-04", "Radio", "Transmit power sweep", "7.2", "Radio sweep runner and real nodes"),
    (
        "SEC-01",
        "Security",
        "Protected vs unprotected exchange",
        "7.1, 7.2",
        "Firmware security profiles",
    ),
    ("SEC-02", "Security", "Altered-packet rejection", "7.1, 7.2", "Controlled frame mutation"),
    (
        "SEC-03",
        "Security",
        "Replay rejection",
        "7.1, 7.2",
        "Retained-frame injection and replay checks",
    ),
    ("SEC-04", "Security", "Cryptographic processing overhead", "7.1", "On-node crypto timing"),
    (
        "PKT-01",
        "Packets",
        "Message size and reconstruction",
        "7.1, 7.2",
        "Message reassembly firmware",
    ),
    ("PKT-02", "Packets", "Fragmentation and missing fragments", "7.2", "Fragment fault injection"),
    (
        "PKT-03",
        "Packets",
        "Acknowledgment and retry policies",
        "7.1, 7.2",
        "ACK/retry instrumentation",
    ),
    ("TIME-01", "Timing", "Round-trip delay", "7.1", "Node-local echo timestamps"),
    ("TIME-02", "Timing", "Synchronized one-way delay", "7.1", "Validated clock synchronization"),
    (
        "MEM-01",
        "Memory",
        "Buffer and memory constraints",
        "6, 7.1",
        "ESP-IDF memory instrumentation",
    ),
    ("VOICE-01", "Voice", "Local capture and playback", "1.3, 6", "ESP-IDF I2S capture/playback"),
    (
        "VOICE-02",
        "Voice",
        "Compressed voice vs known data",
        "1.3, 7.2",
        "Codec and voice RF pipeline",
    ),
    ("VOICE-03", "Voice", "Sustained voice feasibility", "7.1", "Codec rate and buffer telemetry"),
    (
        "VOICE-04",
        "Voice",
        "Voice delay and intelligibility",
        "7.1",
        "Recovered audio and stage timing",
    ),
    (
        "MODEL-01",
        "Models",
        "Airtime and delivery prediction",
        "7.1",
        "Validated modem timing model",
    ),
    (
        "OPS-01",
        "Operations",
        "Faults, reset and recovery",
        "6",
        "Node and transport fault injection",
    ),
]


# Local checks are performed independently; RF workloads still require a pair.
LOCAL_TESTS = {"IF-01", "SEC-04", "MEM-01", "VOICE-01", "OPS-01"}
MIXED_TESTS = {"MEM-01", "OPS-01"}
CAPABILITIES = {
    "SEC-04": ["security_gcm"],
    "MEM-01": ["memory_stats"],
    "VOICE-01": ["audio_capture", "audio_playback", "codec2_3200"],
}


def required_nodes(code: str, workload: str = "default") -> int:
    if code not in {row[0] for row in ROWS}:
        raise ValueError("Unknown experiment ID")
    if workload == "local" and code not in LOCAL_TESTS:
        raise ValueError(f"{code} requires a two-node workload")
    if workload == "rf" and code in LOCAL_TESTS - MIXED_TESTS:
        raise ValueError(f"{code} is a local procedure")
    return 1 if code in LOCAL_TESTS and workload != "rf" else 2


def catalog() -> list[dict]:
    return [
        {
            "id": code,
            "group": group,
            "title": title,
            "cdr": reference,
            "available": code == "IF-01",
            "mode": "hardware",
            "required_nodes": required_nodes(code),
            "node_requirement": (
                "One node for local cases; two for RF cases"
                if code in MIXED_TESTS
                else "One node at a time"
                if code in LOCAL_TESTS
                else "Two nodes"
            ),
            "required_capabilities": CAPABILITIES.get(
                code, ["radio"] if code not in LOCAL_TESTS else []
            ),
            "scope": "diagnostic check only; full IF-01 qualification pending"
            if code == "IF-01"
            else "physical procedure runner pending",
            "blocker": None
            if code == "IF-01"
            else (
                f"{blocker or 'Physical execution adapter and firmware support'}; "
                "physical procedure runner pending"
            ),
            "hardware_status": "physical procedure validation pending",
            "hardware_validated": False,
        }
        for code, group, title, reference, blocker in ROWS
    ]
