import copy
import tempfile
import unittest
import winreg
from gpu_core import (apply_plan, check_plan, dx_string, gl_plan, operation, export_bat,
                      dx_matches, dx_reset_plan, restore_plan, adapters, gl_preflight, CLASS, PCI, PREF, GLOBAL)


class FakeRegistry:
    def __init__(self):
        self.data = {}
        self.fail = None

    def read(self, root, path, name, view=64):
        return self.data.get((root, path, name, view))

    def write(self, root, path, name, view, value):
        if name == self.fail:
            self.fail = None
            raise PermissionError('simulated denied write')
        key = (root, path, name, view)
        if value is None:
            self.data.pop(key, None)
        else:
            self.data[key] = tuple(value)

    def children(self, root, path):
        prefix = path + '\\'
        return sorted({p[len(prefix):].split('\\')[0] for r, p, n, v in self.data
                       if r == root and p.startswith(prefix)})


class CoreTests(unittest.TestCase):
    def test_preserve_unrelated_dx_settings(self):
        self.assertEqual(dx_string('HighPerfAdapter=OLD;SwapEffectUpgradeEnable=1;Other=7;', 'NEW'),
                         'HighPerfAdapter=NEW;SwapEffectUpgradeEnable=1;Other=7;')

    def test_default_dx_settings(self):
        self.assertEqual(dx_string('', 'A'), 'HighPerfAdapter=A;SwapEffectUpgradeEnable=0;')

    def test_write_verify_backup_and_restore(self):
        import json
        db = FakeRegistry()
        db.write('HKCU', 'Test', 'existing', 64, ['original', winreg.REG_SZ])
        before = copy.deepcopy(db.data)
        plan = [operation('HKCU', 'Test', 'existing', 'new'), operation('HKCU', 'Test', 'added', 1, winreg.REG_DWORD)]
        with tempfile.TemporaryDirectory() as folder:
            backup = apply_plan(db, plan, folder, 'test')
            self.assertFalse(check_plan(db, plan))
            saved = json.loads(backup.read_text(encoding='utf-8'))
            apply_plan(db, saved['before'], folder, 'undo')
            self.assertEqual(before, db.data)

    def test_partial_failure_rolls_back(self):
        db = FakeRegistry()
        db.write('HKCU', 'Test', 'first', 64, ['old', winreg.REG_SZ])
        before = copy.deepcopy(db.data)
        db.fail = 'second'
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(OSError):
                apply_plan(db, [operation('HKCU', 'Test', 'first', 'new'), operation('HKCU', 'Test', 'second', 'no')], folder, 'test')
        self.assertEqual(before, db.data)

    def test_gl_both_views_and_all_adapters(self):
        gpu = dict(key='0001', name='Example', gl='a.dll', gl32='a32.dll', did='10DE&ABCD&12345678')
        other = dict(gpu, key='0002', gl='b.dll', gl32='b32.dll')
        plan = gl_plan([gpu, other], gpu)
        self.assertEqual(len(plan), 16)
        self.assertEqual(sum(op['value'] is None for op in plan), 4)
        self.assertEqual({op['view'] for op in plan if op['name'] == 'DLL'}, {32, 64})
        script = export_bat('GL', gpu, [gpu, other])
        from test_bat_export import decode_payload
        self.assertIn('Registry32', decode_payload(script))
        self.assertIn('Administrator', script)
        self.assertIn('10DE&ABCD&12345678', decode_payload(export_bat('DX', gpu, [gpu])))

    def test_incomplete_driver_is_rejected(self):
        gpu = dict(key='0001', name='Missing', gl='a.dll', gl32='')
        with self.assertRaises(ValueError):
            gl_plan([gpu], gpu)

    def test_verify_detects_mismatch(self):
        self.assertEqual(len(check_plan(FakeRegistry(), [operation('HKCU', 'Test', 'x', 1)])), 1)

    def test_dx_verification_ignores_field_order_and_missing_unrelated_option(self):
        db = FakeRegistry()
        db.write('HKCU', PREF, GLOBAL, 64, ['Other=1;HighPerfAdapter=abcd;', winreg.REG_SZ])
        self.assertTrue(dx_matches(db, dict(did='ABCD')))

    def test_dx_reset_preserves_other_fields(self):
        db = FakeRegistry()
        db.write('HKCU', PREF, GLOBAL, 64, ['Other=1;HighPerfAdapter=ABCD;AutoHDR=1;', winreg.REG_SZ])
        self.assertEqual(dx_reset_plan(db)[0]['value'][0], 'Other=1;AutoHDR=1;')

    def test_gl_covers_other_32bit_only_device(self):
        gpu = dict(key='0001', gl='x64.dll', gl32='x32.dll')
        other = dict(key='0002', gl='', gl32='other32.dll')
        plan = gl_plan([gpu, other], gpu)
        self.assertTrue(any(op['path'].endswith('0002') and op['name'] == 'OpenGLDriverNameWow' and op['value'] is None for op in plan))

    def test_disconnected_device_is_not_target(self):
        gpu = dict(key='0001', gl='x64.dll', gl32='x32.dll', present=False)
        with self.assertRaises(ValueError):
            gl_plan([gpu], gpu)

    def test_adapter_presence_disambiguates_stale_registry(self):
        db = FakeRegistry()
        driver = CLASS.split('\\')[-1] + '\\0001'
        device = 'VEN_10DE&DEV_ABCD&SUBSYS_12345678'
        db.write('HKLM', PCI + '\\' + device + '\\instance', 'Driver', 64, [driver, winreg.REG_SZ])
        db.write('HKLM', CLASS + '\\0001', 'DriverDesc', 64, ['Example GPU', winreg.REG_SZ])
        self.assertFalse(adapters(db, set())[0]['present'])
        self.assertTrue(adapters(db, {('PCI\\' + device + '\\instance').upper()})[0]['present'])

    def test_history_restore_roundtrip_and_external_change_guard(self):
        db = FakeRegistry()
        plan = [operation('HKCU', PREF, GLOBAL, 'HighPerfAdapter=TEST;')]
        with tempfile.TemporaryDirectory() as folder:
            path = apply_plan(db, plan, folder, 'DirectX')
            restored = restore_plan(db, path)
            self.assertIsNone(restored[0]['value'])
            db.write('HKCU', PREF, GLOBAL, 64, ['External=1;', winreg.REG_SZ])
            with self.assertRaisesRegex(ValueError, '已发生变化'):
                restore_plan(db, path)

    def test_history_rejects_foreign_user_and_unmanaged_path(self):
        import json
        db = FakeRegistry()
        with tempfile.TemporaryDirectory() as folder:
            path = apply_plan(db, [operation('HKCU', PREF, GLOBAL, 'x')], folder, 'DirectX')
            data = json.loads(path.read_text(encoding='utf-8'))
            data['identity']['user'] = 'another-user'
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '用户'):
                restore_plan(db, path)
            for name in ('before', 'after'):
                data[name][0]['path'] = 'Software\\SomeOtherApp'
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '范围以外'):
                restore_plan(db, path)

    def test_rollback_silent_failure_is_reported(self):
        class BrokenRollback(FakeRegistry):
            def write(self, root, path, name, view, value):
                if name == 'second':
                    raise OSError('injected failure')
                if value == ['old', winreg.REG_SZ]:
                    return
                super().write(root, path, name, view, value)
        db = BrokenRollback()
        db.data[('HKCU', 'Test', 'first', 64)] = ('old', winreg.REG_SZ)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(OSError, '回滚失败'):
                apply_plan(db, [operation('HKCU', 'Test', 'first', 'new'), operation('HKCU', 'Test', 'second', 'value')], folder, 'test')

    def test_gl_history_checks_driver_version(self):
        db = FakeRegistry()
        gpu = dict(key='0001', gl='x64.dll', gl32='x32.dll')
        db.write('HKLM', CLASS + '\\0001', 'DriverVersion', 64, ['1.0', winreg.REG_SZ])
        with tempfile.TemporaryDirectory() as folder:
            path = apply_plan(db, gl_plan([gpu], gpu), folder, 'OpenGL')
            self.assertEqual(len(restore_plan(db, path)), 12)
            db.write('HKLM', CLASS + '\\0001', 'DriverVersion', 64, ['2.0', winreg.REG_SZ])
            with self.assertRaisesRegex(ValueError, '驱动已更新'):
                restore_plan(db, path)

    def test_preflight_rejects_wrong_architecture_and_missing_files(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'driver.dll'
            data = bytearray(128)
            data[:2] = b'MZ'
            data[0x3c:0x40] = (64).to_bytes(4, 'little')
            data[64:70] = b'PE\0\0' + (0x14c).to_bytes(2, 'little')
            path.write_bytes(data)
            with self.assertRaisesRegex(ValueError, '架构不匹配'):
                gl_preflight(dict(gl=str(path), gl32=str(path)))
            with self.assertRaisesRegex(ValueError, '不存在'):
                gl_preflight(dict(gl=str(path) + '.missing', gl32=str(path)))


if __name__ == '__main__':
    unittest.main()
