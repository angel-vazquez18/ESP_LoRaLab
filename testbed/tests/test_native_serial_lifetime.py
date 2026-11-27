"""The native test port must reject closed writes like a physical serial port."""

import subprocess
import sys
from pathlib import Path


def test_native_serial_write_after_close_raises_without_entering_destroyed_core():
    program = r"""
import sys, tempfile, resource
from pathlib import Path
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
sys.path.insert(0, sys.argv[1])
from test_node_control_native import NativeSerial, native_library
class Factory:
    def mktemp(self, label):
        return Path(tempfile.mkdtemp(prefix="closed-native-" + label))
lib = native_library.__wrapped__(Factory())
serial = NativeSerial(lib)
serial.close()
try:
    serial.write(b"{}\n")
except OSError:
    pass
else:
    raise AssertionError("A closed serial port accepted a write")
"""
    child = subprocess.run(
        [sys.executable, "-c", program, str(Path(__file__).parent)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert child.returncode == 0, (
        f"Closed-port subprocess exited {child.returncode}: {child.stderr[-1000:]}"
    )
