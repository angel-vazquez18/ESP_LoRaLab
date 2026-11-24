"""Package entry-point gates: local checks must never open or discover devices."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import lora_crypto_bench as bench


class PackageLauncherTests(unittest.TestCase):
    def shell(self):
        shell = os.environ.get('LORA_TEST_POWERSHELL') or shutil.which('pwsh') or shutil.which('powershell')
        if not shell:
            self.skipTest('PowerShell not available; set LORA_TEST_POWERSHELL')
        return shell

    def launch(self, *flags):
        return subprocess.run([self.shell(), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                               str(ROOT / 'tools/run_lora_crypto_comparison.ps1'),
                               '-Python', 'definitely-not-a-python-executable', *flags],
                              capture_output=True, text=True, timeout=30)

    def test_no_flag_does_not_invoke_python(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('No hardware action performed', result.stdout)

    def test_conflicting_flags_stop_before_python(self):
        result = self.launch('-Start', '-Check')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Choose -Start or -Check', result.stderr)

    def test_check_only_never_discovers_or_opens_devices(self):
        with patch.object(bench.base, 'discover_nodes') as discover, \
             patch.object(bench.CryptoConnection, 'open') as open_port, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            result = bench.main(['--check-only', '--wav', str(ROOT / 'input/source.wav')])
        self.assertEqual(result, 0)
        discover.assert_not_called()
        open_port.assert_not_called()
        self.assertIn('"ports_opened": false', output.getvalue())


if __name__ == '__main__':
    unittest.main()
