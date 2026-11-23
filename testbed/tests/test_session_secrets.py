"""Secret-bearing session requests must fail without exposing supplied values."""

import asyncio
import json
from uuid import uuid4

import pytest
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.nodes import NodeSession


def test_rejected_session_key_values_never_enter_errors_or_trace(native_library):
    async def scenario():
        peer = NativeSerial(native_library, radio=native_library.native_radio_create())
        node = NodeSession("A", lambda *_: None, lambda _: peer)
        trace = []
        # Public sentinel values, never ordinary run keys.
        sentinels = ["11" * 16, "22" * 16]
        await node.connect("fixture-only-secret-rejection")
        try:
            with pytest.raises(ValueError) as error:
                await node.request(
                    "session.open",
                    {
                        "session_id": "0102030405060708",
                        "peer_device_id": "esp-66778899aabb",
                        "peer_boot_id": "esp-66778899aabb:1",
                        "security": "none",
                        "tx_key_hex": sentinels[0],
                        "rx_key_hex": sentinels[1],
                    },
                    run_id=str(uuid4()),
                    on_record=trace.append,
                )
            saved = json.dumps({"error": str(error.value), "trace": trace})
            assert all(value not in saved for value in sentinels)
            assert not trace and node.rf_run_id is None
        finally:
            await node.close()

    asyncio.run(scenario())


def test_host_protected_setup_stays_blocked_before_trace_until_provisioning_guards(native_library):
    async def scenario():
        peer = NativeSerial(native_library, radio=native_library.native_radio_create())
        node = NodeSession("A", lambda *_: None, lambda _: peer)
        trace = []
        await node.connect("fixture-only-protected-gate")
        try:
            with pytest.raises(ValueError, match="Protected host provisioning is not enabled"):
                await node.request(
                    "session.open",
                    {
                        "session_id": "0102030405060708",
                        "peer_device_id": "esp-66778899aabb",
                        "peer_boot_id": "esp-66778899aabb:1",
                        "security": "aes128_gcm",
                        "tx_key_hex": "11" * 16,
                        "rx_key_hex": "22" * 16,
                    },
                    run_id=str(uuid4()),
                    on_record=trace.append,
                )
            assert not trace and node.rf_run_id is None
        finally:
            await node.close()

    asyncio.run(scenario())
