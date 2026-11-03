from lora_testbed.models import Command
from lora_testbed.protocol import MAX_LINE_BYTES, Decoder, encode


def test_partial_reads_and_multiple_records():
    first = Command(command_id="hello-1", name="hello")
    second = Command(command_id="hello-2", name="hello")
    wire = encode(first)
    decoder = Decoder()
    assert decoder.feed(wire[:8]) == ([], [])
    records, faults = decoder.feed(wire[8:] + encode(second))
    assert faults == []
    assert [record.command_id for record in records] == ["hello-1", "hello-2"]


def test_recover_after_oversized_malformed_and_wrong_version_records():
    valid = encode(Command(command_id="good", name="hello"))
    wire = b"x" * (MAX_LINE_BYTES + 100) + b"\n[]\n\xff\n" + valid.replace(b'"v":1', b'"v":9')
    decoder = Decoder()
    records, faults = decoder.feed(wire + valid)
    assert len(records) == 1
    assert records[0].command_id == "good"
    assert faults == ["line_too_long", "invalid_record", "invalid_record", "invalid_record"]
    assert len(decoder.buffer) == 0


def test_limit_handles_stream_without_newlines():
    decoder = Decoder()
    for _ in range(50):
        decoder.feed(b"x" * MAX_LINE_BYTES)
    assert len(decoder.buffer) == 0
    assert decoder.discarding
    valid = Command(command_id="recovered", name="hello")
    assert decoder.feed(b"\n" + encode(valid))[0] == [valid]
