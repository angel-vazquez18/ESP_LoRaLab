"""Compile and exercise the real firmware core, without a physical serial port."""

import asyncio
import ctypes as C
import hashlib
import json
import os
import platform
import queue
import shutil
import subprocess
import threading
from time import monotonic
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from lora_testbed import control_v2
from lora_testbed.app import create_app
from lora_testbed.nodes import NodeSession
from lora_testbed.paths import REPOSITORY_ROOT as REPO_ROOT


class Heap(C.Structure):
    _fields_ = [
        (name, C.c_uint64) for name in ("free_bytes", "minimum_free_bytes", "largest_free_bytes")
    ] + [("present", C.c_bool)]


NOW = C.CFUNCTYPE(C.c_int64, C.c_void_p)
HASH = C.CFUNCTYPE(C.c_bool, C.c_void_p, C.c_void_p, C.c_size_t, C.c_void_p)
RANDOM = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_size_t)
ALLOC = C.CFUNCTYPE(C.c_void_p, C.c_void_p, C.c_size_t)
FREE = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p)
MEMORY = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(Heap), C.POINTER(Heap), C.POINTER(C.c_uint32))


class Platform(C.Structure):
    _fields_ = [
        ("context", C.c_void_p),
        ("now_us", NOW),
        ("sha256", HASH),
        ("random_bytes", RANDOM),
        ("allocate", ALLOC),
        ("deallocate", FREE),
        ("memory", MEMORY),
    ] + [
        (name, C.c_char_p)
        for name in (
            "device_id",
            "boot_id",
            "firmware_version",
            "firmware_build_id",
            "idf_version",
            "board_manifest_hash",
            "schema_sha256",
            "reset_cause",
        )
    ]


@pytest.fixture(scope="session")
def native_library(tmp_path_factory):
    compiler = shutil.which("clang") or shutil.which("cc")
    main = REPO_ROOT / "firmware/lora_node/main"
    cjson = REPO_ROOT / "firmware/lora_node/managed_components/espressif__cjson/cJSON"
    if compiler is None or not (cjson / "cJSON.c").exists():
        pytest.skip("Native firmware checks require a C compiler and IDF-managed cJSON sources")
    output = tmp_path_factory.mktemp("firmware-core") / "node_control.so"
    toolchain = [compiler]
    if platform.system() == "Darwin":
        toolchain = ["xcrun", "--sdk", "macosx", "clang"]
    compiled = subprocess.run(
        [
            *toolchain,
            "-shared",
            "-fPIC",
            "-std=c11",
            "-O1",
            "-g",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DCJSON_NESTING_LIMIT=8",
            "-I",
            str(main),
            "-I",
            str(cjson),
            str(main / "protocol/strict_json.c"),
            str(main / "control/node_control.c"),
            str(cjson / "cJSON.c"),
            str(REPO_ROOT / "testbed/tests/native/cjson_allocator.c"),
            "-lm",
            "-o",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert compiled.returncode == 0, compiled.stderr
    lib = C.CDLL(str(output))
    lib.native_allocator_install()
    lib.native_allocator_fail_after.argtypes = [C.c_long]
    lib.native_allocations_live.restype = C.c_long
    lib.node_control_create.argtypes = [C.POINTER(Platform)]
    lib.node_control_create.restype = C.c_void_p
    lib.node_control_destroy.argtypes = [C.c_void_p]
    lib.node_control_feed.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
    lib.node_control_tick.argtypes = [C.c_void_p]
    lib.node_control_link.argtypes = [C.c_void_p, C.c_bool]
    lib.node_control_output.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
    lib.node_control_output.restype = C.c_size_t
    return lib


class NativeNode:
    def __init__(self, lib, realtime=False, boot=1):
        self.lib, self.time, self.realtime = lib, 1_000_000, realtime
        self.origin = monotonic()
        self.boot_id = f"esp-001122334455:{boot}"
        self.client = str(uuid4())
        self.sequence = 0
        self.allocations = {}
        self.allocation_fails = False
        self.callbacks = [
            NOW(lambda _: self.now()),
            HASH(self.hash),
            RANDOM(self.random),
            ALLOC(self.allocate),
            FREE(self.free),
            MEMORY(self.memory),
        ]
        self.platform = Platform(
            None,
            *self.callbacks,
            b"esp-001122334455",
            self.boot_id.encode(),
            b"native-test",
            b"a" * 64,
            b"v6.0.2",
            b"b" * 64,
            control_v2.schema_digest().encode(),
            b"test_fixture",
        )
        self.node = lib.node_control_create(C.byref(self.platform))
        assert self.node

    def now(self):
        return self.time + (int((monotonic() - self.origin) * 1e6) if self.realtime else 0)

    @staticmethod
    def hash(_, source, length, target):
        C.memmove(target, hashlib.sha256(C.string_at(source, length)).digest(), 32)
        return True

    @staticmethod
    def random(_, target, length):
        C.memmove(target, os.urandom(length), length)

    def allocate(self, _, length):
        if self.allocation_fails:
            return None
        buffer = C.create_string_buffer(length)
        pointer = C.addressof(buffer)
        self.allocations[pointer] = buffer
        return pointer

    def free(self, _, pointer):
        assert pointer in self.allocations
        del self.allocations[pointer]

    def memory(self, _, internal, psram, failures):
        used = sum(C.sizeof(b) for b in self.allocations.values())
        internal[0] = Heap(200000 - used, 130000, 120000, True)
        psram[0] = Heap(2095000, 2095000, 2064384, True)
        failures[0] = int(self.allocation_fails)

    def command(self, name="hello", args=None, client=None, **updates):
        self.sequence += 1
        return {
            "v": 2,
            "kind": "command",
            "command_id": str(uuid4()),
            "client_id": client or self.client,
            "command_seq": self.sequence,
            "target_boot_id": None if name == "hello" else self.boot_id,
            "run_id": None,
            "name": name,
            "args": {} if args is None else args,
            **updates,
        }

    def feed(self, data):
        self.lib.node_control_feed(self.node, data, len(data))

    def drain(self):
        output = C.create_string_buffer(4096)
        records = []
        while length := self.lib.node_control_output(self.node, output, len(output)):
            wire = output.raw[:length]
            assert wire.endswith(b"\n") and len(wire) <= 4096
            record = json.loads(wire)
            control_v2.ADAPTER.validate_python(record)
            records.append(record)
        return records

    def send(self, command):
        self.feed(json.dumps(command, separators=(",", ":")).encode() + b"\n")
        return self.drain()

    def request(self, name="hello", args=None, **updates):
        records = self.send(self.command(name, args, **updates))
        return next(r for r in records if r["kind"] == "reply")

    def claim(self):
        assert self.request("control.claim", {"node_role": "A"})["ok"]

    def tick(self, advance=0):
        self.time += advance
        self.lib.node_control_tick(self.node)

    def close(self):
        self.lib.node_control_destroy(self.node)
        assert not self.allocations
        assert self.lib.native_allocations_live() == 0
        self.node = None


@pytest.fixture
def native(native_library):
    node = NativeNode(native_library)
    yield node
    node.close()


def test_identity_claim_status_and_release(native):
    hello = native.request()["result"]
    assert hello["schema_sha256"] == control_v2.schema_digest()
    assert hello["board_revision"] is None and not hello["capabilities"]["radio"]
    assert native.request("status.get")["error"]["code"] == "NOT_OWNER"
    native.claim()
    status = native.request("status.get")["result"]
    assert status["state"] == "idle" and status["node_role"] == "A"
    assert status["memory"]["psram"]["free_bytes"] == 2095000
    assert native.request("control.release")["ok"]
    assert not native.request()["result"]["claimed"]


@pytest.mark.parametrize(
    "bad",
    [
        b"",
        b"hello",
        b"[]",
        b"{} trailing",
        b"\xef\xbb\xbf{}",
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1e999}',
        b'{"x":01}',
        b'{"x":1.}',
        b'{"x":.1}',
        b'{"x":+1}',
        b'{"x":1e}',
        b'{"x":--1}',
        b'{"x":true,}',
        b'{"x":/*c*/1}',
        b'{"x":"\xff"}',
        b'{"x":"\xc0\x80"}',
        b'{"x":"\xed\xa0\x80"}',
        b'{"x":"\xf4\x90\x80\x80"}',
        b'{"x":"raw\tcontrol"}',
        b'{"x":"\\u0000"}',
        b'{"x":"\\ud800"}',
        b'{"x":"\\udc00"}',
        b'{"x":1,"x":2}',
        b'{"x":{"a":1,"\\u0061":2}}',
        b'{"x": "a\x00b"}',
        b'{"x": [[[[[[[[0]]]]]]]]}',
    ],
)
def test_strict_rejections_recover_to_next_record(native, bad):
    wire = json.dumps(native.command()).encode() + b"\n"
    native.feed(bad + b"\n" + wire)
    replies = [r for r in native.drain() if r["kind"] == "reply"]
    assert len(replies) == 1 and replies[0]["ok"]


def test_framing_boundaries_partial_crlf_and_oversize(native):
    command = native.command()
    wire = json.dumps(command).encode()
    for byte in wire + b"\r\n":
        native.feed(bytes([byte]))
    assert next(r for r in native.drain() if r["kind"] == "reply")["ok"]
    for crlf in (False, True):
        wire = json.dumps(native.command()).encode()
        ending = b"\r\n" if crlf else b"\n"
        bounded = wire + b" " * (4096 - len(wire) - len(ending)) + ending
        assert len(bounded) == 4096
        native.feed(bounded)
        assert next(r for r in native.drain() if r["kind"] == "reply")["ok"]
    native.feed(b"x" * 10000 + b"\n" + json.dumps(native.command()).encode() + b"\n")
    assert next(r for r in native.drain() if r["kind"] == "reply")["ok"]
    native.claim()
    assert native.request("status.get")["result"]["traffic"]["rx_oversized"] == 1


@pytest.mark.parametrize(
    ("update", "code"),
    [
        ({"v": 3}, "UNSUPPORTED_VERSION"),
        ({"kind": "Command"}, "INVALID_ARGUMENT"),
        ({"client_id": "not-a-uuid"}, "INVALID_ARGUMENT"),
        ({"target_boot_id": 12}, "INVALID_ARGUMENT"),
        ({"run_id": "invalid"}, "INVALID_ARGUMENT"),
        ({"args": []}, "INVALID_ARGUMENT"),
        ({"extra": True}, "INVALID_ARGUMENT"),
        ({"name": ""}, "INVALID_ARGUMENT"),
    ],
)
def test_envelope_errors_are_correlated(native, update, code):
    command = native.command(**update)
    reply = next(r for r in native.send(command) if r["kind"] == "reply")
    assert reply["command_id"] == command["command_id"]
    assert reply["error"]["code"] == code


def test_claim_conflicts_stale_boot_arguments_and_missing_capabilities(native):
    native.claim()
    assert (
        native.request("control.claim", {"node_role": "B"}, client=str(uuid4()))["error"]["code"]
        == "BUSY"
    )
    assert (
        native.request("status.get", target_boot_id="esp-001122334455:2")["error"]["code"]
        == "STALE_BOOT"
    )
    assert native.request("control.keepalive", {"unused": 1})["error"]["code"] == "INVALID_ARGUMENT"
    assert native.request("audio.capture")["error"]["code"] == "MISSING_CAPABILITY"
    assert native.request("not.a.command")["error"]["code"] == "UNSUPPORTED_COMMAND"


def test_duplicate_exact_bytes_conflict_and_eviction_fence(native):
    claim = native.command("control.claim", {"node_role": "A"})
    first = native.send(claim)[0]
    native.tick(1000000)
    assert native.send(claim)[0] == first
    changed = {**claim, "args": {"node_role": "B"}}
    assert native.send(changed)[0]["error"]["code"] == "COMMAND_CONFLICT"
    for _ in range(17):
        assert native.request("control.keepalive")["ok"]
    assert native.send(claim)[0]["error"]["code"] == "COMMAND_EXPIRED"
    release = native.command("control.release")
    result = native.send(release)[0]
    assert native.send(release)[0] == result
    assert not native.request()["result"]["claimed"]


def test_probe_completes_with_verified_content_and_freed_allocation(native):
    native.claim()
    accepted = native.request(
        "diag.run", {"kind": "memory_probe", "iterations": 3, "payload_bytes": 1024}
    )
    assert accepted["ok"] and accepted["result"]["deadline_us"] == 31000000
    operation_id = accepted["result"]["operation_id"]
    assert len(native.allocations) == 1
    events = []
    for _ in range(12):
        native.tick(1000)
        events.extend(native.drain())
    result = next(r["data"] for r in events if r.get("name") == "operation.result")
    assert result["status"] == "completed" and result["operation_id"] == operation_id
    assert result["result"]["verified_bytes"] == 3072
    assert result["result"]["iterations_completed"] == 3
    assert not native.allocations


def test_probe_detects_corruption_and_recovers(native):
    native.claim()
    native.request("diag.run", {"kind": "memory_probe", "iterations": 1, "payload_bytes": 512})
    native.tick()
    next(iter(native.allocations.values()))[0] = b"\xff"
    native.tick()
    event = next(r for r in native.drain() if r.get("name") == "operation.result")
    assert event["data"]["status"] == "failed"
    assert event["data"]["error"]["code"] == "INTERNAL_ERROR"
    assert not native.allocations
    assert native.request("status.get")["result"]["state"] == "idle"


@pytest.mark.parametrize("reason", ["stop", "lease", "disconnect", "deadline"])
def test_active_operation_cleanup(native, reason):
    native.claim()
    result = native.request(
        "diag.run", {"kind": "memory_probe", "iterations": 10000, "payload_bytes": 65536}
    )["result"]
    assert native.request("status.get")["result"]["state"] == "running"
    assert native.request("control.release")["error"]["code"] == "INVALID_STATE"
    if reason == "stop":
        assert native.request("operation.stop", {"operation_id": result["operation_id"]})["ok"]
        assert native.request("operation.stop", {"operation_id": result["operation_id"]})["ok"]
    elif reason == "lease":
        native.tick(5000000)
    elif reason == "disconnect":
        native.lib.node_control_link(native.node, False)
        native.lib.node_control_link(native.node, True)
    else:
        for _ in range(31):
            assert native.request("control.keepalive")["ok"]
            native.tick(1000000)
            native.drain()
    assert not native.allocations
    if reason in ("lease", "disconnect"):
        assert not native.request()["result"]["claimed"]
        native.claim()
    assert native.request("status.get")["result"]["state"] == "idle"


def test_lease_checked_before_dispatch_and_old_claim_never_reexecutes(native):
    claim = native.command("control.claim", {"node_role": "A"})
    assert native.send(claim)[0]["ok"]
    native.time += 5000000
    assert native.send(claim)[0]["error"]["code"] == "COMMAND_EXPIRED"
    assert not native.request()["result"]["claimed"]
    native.claim()


def test_queue_backpressure_drops_visible_and_reply_priority(native):
    native.claim()
    for _ in range(20):
        native.tick(1000000)
    hello = native.command()
    native.feed(json.dumps(hello).encode() + b"\n")
    records = native.drain()
    assert records[0]["kind"] == "reply"
    assert sum(r.get("name") == "health" for r in records) == 8
    native.claim()
    status = native.request("status.get")["result"]
    assert status["telemetry_drops"] >= 12
    for _ in range(8):
        native.feed(json.dumps(native.command()).encode() + b"\n")
    assert len([r for r in native.drain() if r["kind"] == "reply"]) == 4
    assert native.request("status.get")["result"]["traffic"]["rx_backpressure"] == 4


def test_allocation_failure_has_no_operation_effect(native):
    native.claim()
    native.allocation_fails = True
    reply = native.request(
        "diag.run", {"kind": "memory_probe", "iterations": 1, "payload_bytes": 65536}
    )
    assert reply["error"]["code"] == "ALLOCATION_FAILED"
    assert not native.allocations
    assert native.request("status.get")["result"]["state"] == "idle"


class NativeSerial:
    """Test-only transport joining NodeSession to the production C core."""

    def __init__(self, lib):
        self.core = NativeNode(lib, realtime=True)
        self.lock = threading.RLock()
        self.queue = queue.Queue()
        self.closed = False

    def _pump(self):
        self.core.tick()
        for record in self.core.drain():
            self.queue.put(json.dumps(record).encode() + b"\n")

    def write(self, wire):
        with self.lock:
            self.core.feed(wire)
            self._pump()
        return len(wire)

    def read(self, count):
        with self.lock:
            if self.closed:
                return b""
            self._pump()
        try:
            return self.queue.get(timeout=0.01)
        except queue.Empty:
            return b""

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                self.core.close()


def test_real_host_session_and_core_complete_cancel_and_shutdown(native_library):
    async def scenario():
        serial = NativeSerial(native_library)
        events = []
        session = NodeSession("B", lambda _, event: events.append(event), lambda _: serial)
        await session.connect("isolated-native-core")
        assert session.wire_profile == "node_control" and session.health.node_role == "B"
        await session.request(
            "diag.run", {"kind": "memory_probe", "iterations": 2, "payload_bytes": 512}
        )
        for _ in range(50):
            if session.operation_results:
                break
            await asyncio.sleep(0.01)
        assert session.operation_results[-1]["status"] == "completed"
        assert session.active_operation is None
        await session.request(
            "diag.run", {"kind": "memory_probe", "iterations": 10000, "payload_bytes": 65536}
        )
        assert session.active_operation
        await session.close()
        assert serial.closed and not serial.core.allocations
        assert any(e["name"] == "operation.result" for e in events)

    asyncio.run(scenario())


def test_api_uses_same_control_session_and_validates_bounds(native_library, tmp_path):
    serial = NativeSerial(native_library)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        host.physical["A"].opener = lambda _: serial
        client.portal.call(host.physical["A"].connect, "isolated-native-core")
        response = client.post(
            "/api/nodes/A/memory-probe", json={"iterations": 10000, "payload_bytes": 65536}
        )
        assert response.status_code == 200
        operation_id = response.json()["operation_id"]
        assert client.post("/api/nodes/A/memory-probe", json={}).status_code == 409
        assert client.post("/api/nodes/A/memory-probe", json={"iterations": 0}).status_code == 422
        response = client.post("/api/nodes/A/operation/stop", json={"operation_id": operation_id})
        assert response.status_code == 200
        assert (
            client.get("/api/protocol/v2/control").json()["schema_sha256"]
            == control_v2.schema_digest()
        )
    assert serial.closed


def test_json_allocations_released_across_repeated_valid_and_invalid_records(native):
    for _ in range(1000):
        assert native.request()["ok"]
        native.feed(b'{"duplicate":1,"duplicate":2}\n')
        native.drain()
        assert native.lib.native_allocations_live() == 0


def test_every_json_allocation_failure_before_acceptance_has_no_effect(native_library):
    for failure_position in range(160):
        node = NativeNode(native_library)
        try:
            node.claim()
            command = node.command(
                "diag.run", {"kind": "memory_probe", "iterations": 10, "payload_bytes": 65536}
            )
            native_library.native_allocator_fail_after(failure_position)
            node.feed(json.dumps(command).encode() + b"\n")
            native_library.native_allocator_fail_after(-1)
            replies = [r for r in node.drain() if r["kind"] == "reply"]
            if not replies or not replies[0]["ok"]:
                assert not node.allocations
            assert native_library.native_allocations_live() == 0
        finally:
            native_library.native_allocator_fail_after(-1)
            node.close()


def test_depth_eight_allowed_and_nine_rejected(native):
    nested = 0
    for _ in range(6):
        nested = [nested]
    command = native.command(args={"nested": nested})
    replies = [r for r in native.send(command) if r["kind"] == "reply"]
    assert replies[0]["error"]["code"] == "INVALID_ARGUMENT"  # JSON passed; hello takes no args.
    command = native.command(args={"nested": [nested]})
    assert not [r for r in native.send(command) if r["kind"] == "reply"]
    assert native.request()["ok"]


def test_mutating_cache_id_cannot_be_reused_by_a_read_command(native):
    native.claim()
    command = native.command("control.keepalive")
    assert native.send(command)[0]["ok"]
    changed = native.command("status.get", command_id=command["command_id"])
    assert native.send(changed)[0]["error"]["code"] == "COMMAND_CONFLICT"


def test_rejected_mutation_is_cached_before_a_changed_retry(native):
    native.claim()
    command = native.command("control.keepalive", {"unknown": 1})
    reply = native.send(command)[0]
    assert reply["error"]["code"] == "INVALID_ARGUMENT"
    assert native.send(command)[0] == reply
    assert native.send({**command, "args": {}})[0]["error"]["code"] == "COMMAND_CONFLICT"


def test_client_sequence_fences_are_bounded_without_unsafe_eviction(native):
    for _ in range(16):
        native.client = str(uuid4())
        native.claim()
        assert native.request("control.release")["ok"]
    native.client = str(uuid4())
    assert native.request("control.claim", {"node_role": "A"})["error"]["code"] == "RESOURCE_LIMIT"
    assert not native.request()["result"]["claimed"]


def test_main_profile_is_available_to_existing_partial_serial_check(native_library, tmp_path):
    serial = NativeSerial(native_library)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        host.physical["A"].opener = lambda _: serial
        client.portal.call(host.physical["A"].connect, "isolated-native-core")
        response = client.post("/api/procedures/serial", json={"roles": ["A"], "cycles": 1})
        assert response.status_code == 201
        run_id = response.json()["id"]

        async def wait():
            for _ in range(100):
                run = host.procedures.get(run_id)
                if run["status"] != "running":
                    return run
                await asyncio.sleep(0.01)
            raise AssertionError("Partial serial check did not finish")

        run = client.portal.call(wait)
        assert run["status"] == "completed" and run["assessment"] == "pass"
        assert run["identities"]["A"]["schema_sha256"] == control_v2.schema_digest()
        assert not run["full_procedure_passed"] and not run["hardware_validated"]


@pytest.mark.parametrize("value", [True, "1", 1.0, 1.5, 0, -1, 4294967296])
def test_sequence_requires_an_unsigned_integer_token(native, value):
    command = native.command(command_seq=value)
    assert not [r for r in native.send(command) if r["kind"] == "reply"]
    assert native.request()["ok"]


@pytest.mark.parametrize("value", [True, "1", 1.0, 1.5, 0, -1, 10001])
def test_diagnostic_iteration_types_are_strict(native, value):
    native.claim()
    reply = native.request(
        "diag.run", {"kind": "memory_probe", "iterations": value, "payload_bytes": 512}
    )
    assert reply["error"]["code"] == "INVALID_ARGUMENT"
    assert not native.allocations


def test_new_boot_starts_unowned_and_rejects_old_operation(native_library):
    first = NativeNode(native_library)
    first.claim()
    command = first.command(
        "diag.run", {"kind": "memory_probe", "iterations": 10000, "payload_bytes": 65536}
    )
    assert first.send(command)[0]["ok"]
    first.close()
    second = NativeNode(native_library, boot=2)
    try:
        hello = second.request()["result"]
        assert not hello["claimed"] and hello["state"] == "idle"
        assert hello["boot_id"] == "esp-001122334455:2"
        reply = next(r for r in second.send(command) if r["kind"] == "reply")
        assert reply["error"]["code"] == "STALE_BOOT"
        assert not second.allocations
        second.claim()
    finally:
        second.close()


def test_duplicate_probe_acceptance_never_allocates_or_starts_twice(native):
    native.claim()
    command = native.command(
        "diag.run", {"kind": "memory_probe", "iterations": 10000, "payload_bytes": 65536}
    )
    reply = native.send(command)[0]
    allocation = next(iter(native.allocations))
    assert native.send(command)[0] == reply
    assert list(native.allocations) == [allocation]
