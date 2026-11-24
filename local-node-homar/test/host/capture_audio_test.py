import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch
import zlib

source = Path(__file__).resolve().parents[2] / "tools" / "capture_audio.py"
spec = importlib.util.spec_from_file_location("capture_audio", source)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)

class FragmentedPort(io.BytesIO):
    def read(self, count=-1):
        return super().read(min(count, 13))

class ExportTests(unittest.TestCase):
    payload = (bytes(range(256)) * 188)[:48000]

    def packet(self, payload=None, size=48000, trailer=b"\n[PCM_END]\r\n"):
        data = self.payload if payload is None else payload
        header = f"[PCM_BEGIN] bytes={size} rate=8000 bits=16 channels=1 crc32={zlib.crc32(self.payload):08x}\n".encode()
        return b"[HEARTBEAT] ignored\r\n\n" + header + data + trailer

    def test_fragmented_binary(self):
        payload, rate, crc = capture.read_export(FragmentedPort(self.packet()), bytearray())
        self.assertEqual(payload, self.payload)
        self.assertEqual((rate, crc), (8000, zlib.crc32(self.payload)))

    def test_corruption(self):
        corrupt = bytearray(self.payload)
        corrupt[500] ^= 0x80
        with self.assertRaisesRegex(RuntimeError, "CRC mismatch"):
            capture.read_export(FragmentedPort(self.packet(corrupt)), bytearray())

    def test_length_bound(self):
        with self.assertRaisesRegex(RuntimeError, "Unexpected PCM"):
            capture.read_export(FragmentedPort(self.packet(size=100000000)), bytearray())

    def test_truncation(self):
        with patch.object(capture.time, "monotonic", side_effect=range(100)):
            with self.assertRaisesRegex(RuntimeError, "Truncated PCM"):
                capture.read_export(FragmentedPort(self.packet(payload=b"abc", trailer=b"")), bytearray())

    def test_missing_trailer(self):
        with self.assertRaisesRegex(RuntimeError, "Missing/invalid PCM trailer"):
            capture.read_export(FragmentedPort(self.packet(trailer=b"x" * 128)), bytearray())

    def test_pcm_signed_metrics(self):
        samples, metrics = capture.analyze(b"\x00\x80\xff\x7f\x00\x00\x00\x00", 8000)
        self.assertEqual(list(samples), [-32768, 32767, 0, 0])
        self.assertEqual(metrics["zero_percent"], 50)
        self.assertEqual(metrics["rail_percent"], 50)
        self.assertEqual(metrics["largest_adjacent_jump"], 65535)

if __name__ == "__main__":
    unittest.main()
