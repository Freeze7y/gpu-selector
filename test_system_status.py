"""Health and history regressions; use temporary files and read-only fakes."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from gpu_core import CLASS, PCI
import system_status as status


class Registry:
    def __init__(self):
        self.data = {}
        self.tree = {}

    def read(self, root, path, name, view=64):
        return self.data.get((root, path, name))

    def children(self, root, path):
        return self.tree.get(path, [])

    def write(self, **kwargs):
        raise AssertionError('No real or fake registry writes in health tests')


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'uncreated'

    def test_read_only_views_do_not_create_app_data(self):
        self.assertEqual(status.read_logs(self.folder), [])
        self.assertEqual(status.reboot_status(self.folder)['state'], 'none')
        self.assertFalse(self.folder.exists())

    def test_log_unicode_newline_roundtrip_and_exact_export(self):
        path = status.write_log(self.folder, '应用 DirectX', '成功', '第一行\n第二行')
        record = status.read_logs(self.folder)[0]
        self.assertEqual(record['details'], '第一行\n第二行')
        self.assertEqual(len(path.read_text(encoding='utf-8').splitlines()), 1)
        output = Path(self.temp.name) / '导出.jsonl'
        status.export_logs(self.folder, output)
        self.assertEqual(output.read_bytes(), path.read_bytes())
        with self.assertRaises(ValueError):
            status.export_logs(self.folder, path)

    def test_log_keeps_last_records_and_surfaces_corruption(self):
        path = status.write_log(self.folder, '一', '成功')
        with path.open('a', encoding='utf-8') as stream:
            stream.write('bad json\n')
        status.write_log(self.folder, '二', '取消')
        records = status.read_logs(self.folder, limit=2)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['result'], '损坏记录')
        self.assertEqual(records[1]['action'], '二')

    def test_reboot_pending_tolerates_timer_and_wall_clock_jitter(self):
        status.record_gl_change(self.folder, 'OpenGL', dict(boot_utc=1000, uptime_ms=500000, observed_utc=1500))
        self.assertEqual(status.reboot_status(self.folder,
            dict(boot_utc=1000.013, uptime_ms=650000, observed_utc=1650.013))['state'], 'pending')

    def test_uptime_reset_confirms_reboot(self):
        status.record_gl_change(self.folder, 'OpenGL', dict(boot_utc=1000, uptime_ms=500000, observed_utc=1500))
        self.assertEqual(status.reboot_status(self.folder,
            dict(boot_utc=2000, uptime_ms=100000, observed_utc=2100))['state'], 'restarted')

    def test_clock_adjustment_does_not_falsely_confirm_reboot(self):
        status.record_gl_change(self.folder, 'OpenGL', dict(boot_utc=1000, uptime_ms=500000, observed_utc=1500))
        self.assertEqual(status.reboot_status(self.folder,
            dict(boot_utc=2000, uptime_ms=650000, observed_utc=2650))['state'], 'unknown')

    def test_corrupt_reboot_records_are_unknown_never_clear(self):
        self.folder.mkdir()
        path = self.folder / status.REBOOT_NAME
        for payload in ('[]', '{}', 'invalid', json.dumps(dict(schema=1, marker=dict(
                boot_utc=float('nan'), uptime_ms=100, observed_utc=100)))):
            path.write_text(payload, encoding='utf-8')
            self.assertEqual(status.reboot_status(self.folder, {})['state'], 'unknown')

    def fixture(self):
        db = Registry()
        device = 'VEN_1234&DEV_ABCD&SUBSYS_12345678'
        instance = '0001'
        instance_id = 'PCI\\' + device + '\\' + instance
        db.tree[PCI] = [device]
        db.tree[PCI + '\\' + device] = [instance]
        db.data[('HKLM', PCI + '\\' + device + '\\' + instance, 'Driver')] = (
            CLASS.split('\\')[-1] + '\\0000', 1)
        db.data[('HKLM', CLASS + '\\0000', 'DriverVersion')] = ('32.0.1', 1)
        db.data[('HKLM', CLASS + '\\0000', 'DriverDate')] = ('9-6-2026', 1)
        return db, [dict(key='0000', name='GPU', present=True)], instance_id

    def test_health_shows_live_disabled_code(self):
        db, gpus, instance_id = self.fixture()
        with patch('device_presence.present_pci_ids', return_value={instance_id.upper()}), patch(
                'system_status.device_status', return_value=dict(disabled=True, problem=22, started=False)):
            row = status.health_rows(gpus, db)[0]
        self.assertTrue(row['present'])
        self.assertTrue(row['disabled'])
        self.assertEqual(row['problem'], 22)
        self.assertEqual(row['version'], '32.0.1')

    def test_health_does_not_call_devnode_for_disconnected_device(self):
        db, gpus, _ = self.fixture()
        with patch('device_presence.present_pci_ids', return_value=set()), patch('system_status.device_status') as probe:
            row = status.health_rows(gpus, db)[0]
        probe.assert_not_called()
        self.assertFalse(row['present'])
        self.assertIsNone(row['problem'])

    def test_health_read_error_never_reports_healthy(self):
        db, gpus, instance_id = self.fixture()
        with patch('device_presence.present_pci_ids', return_value={instance_id.upper()}), patch(
                'system_status.device_status', side_effect=OSError('device removed')):
            row = status.health_rows(gpus, db)[0]
        self.assertIn('未知', row['status'])
        self.assertEqual(row['error'], 'device removed')
        self.assertIsNone(row['disabled'])

    def test_native_problem_number_is_ignored_without_problem_flag(self):
        cfg = Mock()
        def locate(node, instance, flags):
            ctypes.cast(node, ctypes.POINTER(wintypes.ULONG))[0] = 17
            return 0
        def get_status(flags, problem, node, reserved):
            ctypes.cast(flags, ctypes.POINTER(wintypes.ULONG))[0] = status.DN_STARTED
            ctypes.cast(problem, ctypes.POINTER(wintypes.ULONG))[0] = 22
            return 0
        cfg.CM_Locate_DevNodeW.side_effect = locate
        cfg.CM_Get_DevNode_Status.side_effect = get_status
        with patch('system_status.ctypes.WinDLL', return_value=cfg):
            row = status.device_status('PCI\\TEST')
        self.assertEqual(row['problem'], 0)
        self.assertFalse(row['disabled'])
        self.assertTrue(row['started'])

    def test_native_devnode_failure_raises_instead_of_showing_started(self):
        cfg = Mock()
        cfg.CM_Locate_DevNodeW.return_value = 13
        with patch('system_status.ctypes.WinDLL', return_value=cfg):
            with self.assertRaises(OSError):
                status.device_status('PCI\\TEST')
        cfg.CM_Get_DevNode_Status.assert_not_called()


if __name__ == '__main__':
    unittest.main()
