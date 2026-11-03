"""Metrics derived from recorded events, never requested packet counts."""

from .models import NodeEvent


class Metrics:
    def __init__(self):
        self.sent: set[tuple[str, int]] = set()
        self.received: dict[tuple[str, int], int] = {}
        self.duplicates = 0
        self.first_tx_us: int | None = None
        self.last_tx_us: int | None = None
        self.window_us: int | None = None
        self.rssi_dbm: float | None = None
        self.snr_db: float | None = None

    def accept(self, event: NodeEvent):
        data = event.data
        if event.name == "run_summary" and data.get("role") == "sender":
            self.window_us = data["measurement_window_us"]
        elif event.name in ("tx_done", "rx_valid"):
            key = (data["origin_node"], data["packet_seq"])
            if event.name == "tx_done":
                self.sent.add(key)
                if self.first_tx_us is None:
                    self.first_tx_us = event.uptime_us
                self.last_tx_us = event.uptime_us
            elif key in self.received:
                self.duplicates += 1
            else:
                self.received[key] = data["payload_bytes"]
                self.rssi_dbm = data["rssi_dbm"]
                self.snr_db = data["snr_db"]

    def snapshot(self) -> dict:
        matched = self.sent.intersection(self.received)
        useful_bytes = sum(self.received[key] for key in matched)
        duration = self.window_us
        if duration is None and self.first_tx_us is not None and self.last_tx_us is not None:
            duration = self.last_tx_us - self.first_tx_us
        return {
            "sent": len(self.sent),
            "received": len(matched),
            "missing": len(self.sent - matched),
            "duplicates": self.duplicates,
            "useful_bytes": useful_bytes,
            "pdr": len(matched) / len(self.sent) if self.sent else None,
            "throughput_bps": useful_bytes * 8 * 1_000_000 / duration if duration else None,
            "measurement_window_us": duration,
            "rssi_dbm": self.rssi_dbm,
            "snr_db": self.snr_db,
            "timing_basis": "simulator sender window; artificial pacing, not RF airtime",
        }
