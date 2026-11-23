"""USB identity helpers for the isolated LoRa bench.

Extracted verbatim from the source project; no audio CLI or serial-port opening.
Device enumeration occurs only when discover_nodes() is explicitly called.
"""
import re
from serial.tools import list_ports


KNOWN_NODES = {
    "8CFD49B5B78C": {"label": "Heltec-A", "assigned_port": "COM6"},
    "441BF66F99E4": {"label": "Heltec-B", "assigned_port": "COM7"},
}


def normalized_mac(value):
    return re.sub(r"[^0-9A-Fa-f]", "", value or "").upper()


def discover_nodes(ports):
    available = {item.device.upper(): item for item in list_ports.comports()}
    result = []
    seen_serials = set()
    for port_name in ports:
        device = available.get(port_name.upper())
        if device is None:
            raise RuntimeError(f"{port_name} is not a connected serial device")
        hardware_serial = normalized_mac(device.serial_number)
        if (device.vid, device.pid) != (0x303A, 0x1001):
            raise RuntimeError(f"{port_name} is not the expected Espressif USB Serial/JTAG device")
        if hardware_serial not in KNOWN_NODES:
            raise RuntimeError(f"{port_name} has an unrecognized USB serial: {device.serial_number}")
        if hardware_serial in seen_serials:
            raise RuntimeError("Both selected ports must refer to different boards")
        seen_serials.add(hardware_serial)
        node = KNOWN_NODES[hardware_serial]
        result.append({
            "port": device.device,
            "label": node["label"],
            "assigned_port": node["assigned_port"],
            "port_matches_assignment": device.device.upper() == node["assigned_port"],
            "usb_serial": device.serial_number,
            "mac_normalized": hardware_serial,
            "description": device.description,
            "hardware_id": device.hwid,
        })
    return result
