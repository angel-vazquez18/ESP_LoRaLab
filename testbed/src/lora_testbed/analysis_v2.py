"""Independent v2 event reconciliation and payload assertions."""

import hashlib

from .adapters import NodeFailure
from .experiments_v2 import KnownDataPlan, known_data


class RunMetrics:
    def __init__(self, plan: KnownDataPlan, identities: dict):
        self.plan, self.identities = plan, identities
        self.sender, self.receiver = ("A", "B") if plan.spec.direction == "A_TO_B" else ("B", "A")
        self.sequences = dict.fromkeys("AB", 0)
        self.sent = set()
        self.received = {}
        self.delivered = {}
        self.verified = {}
        self.baseline_drops = dict.fromkeys("AB", 0)
        self.session_id = None
        self.revisions = {}
        self.failed = set()
        self.first_tx = self.last_tx = None
        self.attempts = self.duplicates = self.duplicate_events = 0
        self.reasons = []
        self.content_failures = []
        self.summaries = {}
        self.rssi = self.snr = None
        self.events = 0

    def invalidate(self, reason):
        if reason not in self.reasons and len(self.reasons) < 32:
            self.reasons.append(reason)

    def accept(self, event):
        role = event["node_role"]
        expected = self.identities.get(role)
        if expected is None or (event["device_id"], event["boot_id"]) != (
            expected["device_id"],
            expected["boot_id"],
        ):
            self.invalidate("Device or boot changed")
            raise NodeFailure("STALE_BOOT", "Node identity changed during the run")
        seq = event["event_seq"]
        if seq <= self.sequences[role]:
            self.duplicate_events += 1
            return False
        if self.sequences[role] and seq != self.sequences[role] + 1:
            self.invalidate(f"{role} event sequence gap")
        self.sequences[role] = seq
        self.events += 1
        name, data = event["name"], event["data"]
        if (
            data.get("session_id") is not None
            and self.session_id is not None
            and data["session_id"] != self.session_id
        ):
            self.invalidate("Event belongs to another RF session")
            raise NodeFailure("SESSION_MISMATCH", "Event RF session does not match")
        if name == "health":
            if data["telemetry_drops"] > self.baseline_drops[role]:
                self.invalidate(f"{role} reported telemetry drops")
            return True
        if name == "tx.attempt":
            if role != self.sender or data["frame_type"] != "data":
                self.invalidate("Unexpected transmitting role or frame type")
                return True
            self.attempts += 1
            if data["status"] == "completed":
                self.sent.add((role, data["session_id"], data["frame_seq"]))
                if self.first_tx is None:
                    self.first_tx = data["tx_command_us"]
                self.last_tx = data["tx_done_us"]
        elif name == "rx.frame":
            self.rssi, self.snr = data["rssi_dbm"], data["snr_db"]
        elif name == "rx.accepted":
            key = (data["source_role"], data["session_id"], data["frame_seq"])
            if role != self.receiver or key in self.received:
                self.content_failures.append("Repeated acceptance or wrong receiving role")
            else:
                self.received[key] = data["payload_bytes"]
        elif name == "rx.rejected" and data["reason"] == "DUPLICATE":
            self.duplicates += 1
        elif name == "message.result":
            message = data["message_id"]
            if data["status"] == "delivered":
                if role != self.receiver or message in self.delivered:
                    self.content_failures.append("Repeated delivery or wrong receiving role")
                if not 1 <= message <= self.plan.spec.message_count:
                    self.content_failures.append("Unexpected message identity")
                else:
                    expected_hash = hashlib.sha256(
                        known_data(
                            self.plan.spec.source_seed, message, self.plan.spec.message_bytes
                        )
                    ).hexdigest()
                    if (
                        data["sha256"] != expected_hash
                        or data["message_bytes"] != self.plan.spec.message_bytes
                    ):
                        self.content_failures.append(f"Message {message} content mismatch")
                    else:
                        self.verified[message] = data["message_bytes"]
                self.delivered[message] = data["message_bytes"]
            else:
                self.failed.add(message)
        elif name == "run.summary":
            self.summaries[role] = data
            expected_role = "sender" if role == self.sender else "receiver"
            if data["role"] != expected_role or data["config_revision"] != self.revisions.get(
                role, data["config_revision"]
            ):
                self.invalidate(f"{role} summary role or configuration differs")
            if data["telemetry_drops"] > self.baseline_drops[role] or data["validity_reasons"]:
                self.invalidate(f"{role} summary reports incomplete/invalid evidence")
        return True

    def reconcile(self):
        tx, rx = self.summaries.get(self.sender), self.summaries.get(self.receiver)
        if not tx or not rx:
            self.invalidate("Missing final node summary")
            return
        expected = [
            (tx["original_packets"], len(self.sent)),
            (tx["tx_attempts"], self.attempts),
            (rx["accepted_fragments"], len(self.received)),
            (rx["delivered_messages"], len(self.delivered)),
            (rx["useful_delivered_bytes"], sum(self.delivered.values())),
            (rx["failed_messages"], len(self.failed)),
        ]
        if any(a != b for a, b in expected):
            self.invalidate("Node summaries disagree with raw events")
        if self.received.keys() - self.sent:
            self.invalidate("Received identity has no confirmed original transmission")

    def snapshot(self):
        matched = self.sent.intersection(self.received)
        window = (
            self.last_tx - self.first_tx
            if self.last_tx is not None and self.first_tx is not None
            else None
        )
        valid = not self.reasons
        usable = valid and window is not None and window > 0
        started = self.summaries.get(self.sender, {}).get("started_messages")
        return {
            "sent": len(self.sent),
            "received": len(matched),
            "attempts": self.attempts,
            "duplicates": self.duplicates,
            "duplicate_events": self.duplicate_events,
            "delivered_messages": len(self.delivered),
            "verified_messages": len(self.verified),
            "failed_messages": len(self.failed),
            "useful_delivered_bytes": sum(self.verified.values()),
            "observed_delivered_bytes": sum(self.delivered.values()),
            "pdr": len(matched) / len(self.sent) if self.sent and valid else None,
            "completion_ratio": len(self.verified) / started if started and valid else None,
            "accepted_fragment_bps": sum(self.received[k] for k in matched) * 8e6 / window
            if usable
            else None,
            "goodput_bps": sum(self.verified.values()) * 8e6 / window if usable else None,
            "measurement_window_us": window,
            "rssi_dbm": self.rssi,
            "snr_db": self.snr,
            "content_failures": len(self.content_failures),
            "validity_reasons": self.reasons.copy(),
            "timing_basis": "Virtual sender clock; modeled airtime and explicit synthetic signal",
            "provenance": "simulated",
            "event_count": self.events,
        }

    def assess(self, status):
        self.reconcile()
        complete = status == "completed"
        evidence = complete and not self.reasons
        assertions = [
            {
                "id": "execution",
                "expected": "completed",
                "actual": status,
                "assessment": "pass" if complete else "inconclusive",
            },
            {
                "id": "evidence",
                "expected": "continuous events and reconciled summaries",
                "actual": self.reasons.copy(),
                "assessment": "pass" if evidence else "inconclusive",
            },
            {
                "id": "content",
                "expected": "exact independently generated bytes and unique delivery",
                "actual": self.content_failures[:64],
                "assessment": "fail"
                if self.content_failures
                else "pass"
                if evidence and self.delivered
                else "inconclusive",
            },
            {
                "id": "link_exchange",
                "expected": "at least one verified delivered message",
                "actual": len(self.verified),
                "assessment": "pass"
                if evidence and self.delivered and not self.content_failures
                else "inconclusive",
            },
        ]
        results = {item["assessment"] for item in assertions}
        return (
            "fail" if "fail" in results else "inconclusive" if "inconclusive" in results else "pass"
        ), assertions
