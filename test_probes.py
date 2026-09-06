import ctypes as c
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import dx_probe


class FakeD3D:
    def __init__(self, create_hresult=0, bad_pixel=False):
        self.released = []
        self.unmapped = False
        self.create_hresult = create_hresult
        self.buffer = (c.c_ubyte * 32)()
        for offset in (0, 4, 16, 20):
            self.buffer[offset:offset + 4] = [255, 0, 255, 255]
        if bad_pixel:
            self.buffer[20] = 0

        # Functions, like ctypes exports, accept argtypes/restype attributes.
        def create(*args):
            args[7]._obj.value = 1
            args[8]._obj.value = 0xb000
            args[9]._obj.value = 2
            return self.create_hresult
        self.D3D11CreateDevice = create

    def method(self, pointer, slot, *_types):
        def invoke(this, *args):
            if slot == 2:
                self.released.append(this.value)
            elif this.value == 1 and slot == 0:
                args[1]._obj.value = 3
            elif this.value == 3 and slot == 7:
                args[0]._obj.value = 4
            elif this.value == 4 and slot == 8:
                args[0]._obj.description = 'Test hardware'
                args[0]._obj.vendor_id = 0x1002
            elif this.value == 1 and slot == 5:
                args[2]._obj.value = 7 if args[0]._obj.usage == 3 else 5
            elif this.value == 1 and slot == 9:
                args[2]._obj.value = 6
            elif this.value == 2 and slot == 14:
                args[4]._obj.data = c.addressof(self.buffer)
                args[4]._obj.row_pitch = 16
            elif this.value == 2 and slot == 15:
                self.unmapped = True
            return 0
        return invoke


class ProbeTests(unittest.TestCase):
    def test_hresult_failure_is_not_success(self):
        with self.assertRaisesRegex(OSError, '80004005'):
            dx_probe._checked(c.c_int32(0x80004005).value)

    def test_hresult_success(self):
        dx_probe._checked(0)

    def test_null_pixel_mapping_rejected(self):
        with self.assertRaises(RuntimeError):
            dx_probe._read_pixels(dx_probe.MappedResource(None, 8, 0), 2, 2)

    def test_short_row_pitch_rejected(self):
        with self.assertRaises(RuntimeError):
            dx_probe._read_pixels(dx_probe.MappedResource(1, 7, 0), 2, 2)

    def run_fake_probe(self, fake):
        with patch.object(dx_probe.c, 'WinDLL', return_value=fake), \
                patch.object(dx_probe, '_method', side_effect=fake.method):
            return dx_probe.probe()

    def test_all_pixels_and_driver_row_padding_checked(self):
        fake = FakeD3D()
        result = self.run_fake_probe(fake)
        self.assertTrue(result['ok'])
        self.assertEqual(result['render_test']['verified_pixels'], 4)
        self.assertTrue(fake.unmapped)
        self.assertEqual(fake.released, [7, 6, 5, 4, 3, 2, 1])

    def test_corrupt_last_pixel_fails_and_releases_resources(self):
        fake = FakeD3D(bad_pixel=True)
        result = self.run_fake_probe(fake)
        self.assertFalse(result['ok'])
        self.assertFalse(result['render_test']['passed'])
        self.assertIn('回读', result['error'])
        self.assertTrue(fake.unmapped)
        self.assertEqual(len(fake.released), 7)

    def test_device_failure_retains_hresult_and_releases_partial_resources(self):
        fake = FakeD3D(create_hresult=c.c_int32(0x887a0004).value)
        result = self.run_fake_probe(fake)
        self.assertFalse(result['ok'])
        self.assertIn('887A0004', result['error'])
        self.assertEqual(fake.released, [2, 1])
        self.assertFalse(fake.unmapped)

    def test_missing_dll_returns_diagnostic(self):
        with patch.object(dx_probe.c, 'WinDLL', side_effect=OSError('missing')):
            result = dx_probe.probe()
        self.assertFalse(result['ok'])
        self.assertIn('missing', result['error'])

    @unittest.skipUnless(sys.maxsize > 2**32, 'requires 64-bit parent Python')
    def test_x86_runner_rejects_wrong_interpreter_without_loading_x86_dll(self):
        runner = Path(__file__).parent / 'probe32' / 'runner.py'
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'result.json'
            process = subprocess.run([sys.executable, str(runner), str(output)],
                                     capture_output=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads(output.read_text(encoding='utf-8'))
        self.assertFalse(result['ok'])
        self.assertEqual(result['process_bits'], 64)


if __name__ == '__main__':
    unittest.main()
