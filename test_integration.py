"""Integrated preview / transaction / UI persistence tests, with an in-memory registry."""
import copy
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog
import gpu_selector as ui
from gpu_core import PREF, GLOBAL, GL, operation, restore_plan, validate_operations, dx_target
from test_core import FakeRegistry
from ui_preferences import load_preferences, save_preferences, style_for
from system_status import read_logs, reboot_status


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = FakeRegistry()
        self.db.values = lambda *args: []
        self.gpus = [dict(key='0001', name='Test GPU', did='10DE&ABCD&12345678',
                          gl='driver64.dll', gl32='driver32.dll', present=True)]
        self.patches = [patch('gpu_selector.Registry', return_value=self.db),
                        patch('gpu_selector.adapters', return_value=self.gpus),
                        patch('gpu_selector.report', return_value='Report'),
                        patch('gpu_selector.admin', return_value=True)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.window = ui.Window(data_dir=self.tmp.name)
        self.window.timer.stop()
        self.addCleanup(self.close)
        self.plan = [operation('HKCU', PREF, GLOBAL, 'HighPerfAdapter=TEST;')]

    def close(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_cancel_preview_never_writes_or_creates_backup(self):
        with patch('gpu_selector.PreviewDialog') as preview:
            preview.return_value.exec.return_value = QDialog.Rejected
            self.assertFalse(self.window.execute(self.plan, 'test'))
        self.assertEqual(self.db.data, {})
        self.assertFalse(self.window.backup_dir.exists())
        self.assertEqual(read_logs(self.tmp.name)[-1]['result'], '已取消')

    def test_confirm_writes_verifies_logs_and_restores(self):
        with patch('gpu_selector.PreviewDialog') as preview:
            preview.return_value.exec.return_value = QDialog.Accepted
            self.assertTrue(self.window.execute(self.plan, 'test'))
            backup = self.window.last_backup
            self.assertEqual(self.db.read('HKCU', PREF, GLOBAL)[0], 'HighPerfAdapter=TEST;')
            self.assertTrue(self.window.execute(restore_plan(self.db, backup), 'restore'))
        self.assertIsNone(self.db.read('HKCU', PREF, GLOBAL))
        self.assertEqual(read_logs(self.tmp.name)[-1]['result'], '成功')

    def test_change_during_preview_aborts_without_overwriting_external_change(self):
        def external_change():
            self.db.write('HKCU', PREF, GLOBAL, 64, ['External=1;', 1])
            return QDialog.Accepted
        with patch('gpu_selector.PreviewDialog') as preview:
            preview.return_value.exec.side_effect = external_change
            with self.assertRaisesRegex(ValueError, '预览期间'):
                self.window.execute(self.plan, 'test')
        self.assertEqual(self.db.read('HKCU', PREF, GLOBAL)[0], 'External=1;')
        self.assertFalse(self.window.backup_dir.exists())

    def test_noop_skips_preview_and_backup(self):
        self.db.write(**self.plan[0])
        with patch('gpu_selector.PreviewDialog') as preview:
            self.assertTrue(self.window.execute(self.plan, 'test'))
            preview.assert_not_called()
        self.assertFalse(self.window.backup_dir.exists())

    def test_arbitrary_registry_target_is_rejected_before_preview(self):
        plan = [operation('HKCU', r'Software\Microsoft\Windows\CurrentVersion\Run', 'bad', 'bad.exe')]
        with patch('gpu_selector.PreviewDialog') as preview:
            with self.assertRaises(ValueError):
                self.window.execute(plan, 'test')
            preview.assert_not_called()

    def test_app_specific_backup_uses_the_same_safe_restore(self):
        path = r'C:\Games\中文 Game.exe'
        plan = [operation('HKCU', PREF, path, 'GpuPreference=2;AutoHDR=1;')]
        with patch('gpu_selector.PreviewDialog') as preview:
            preview.return_value.exec.return_value = QDialog.Accepted
            self.window.execute(plan, 'app')
        restored = restore_plan(self.db, self.window.last_backup)
        self.assertEqual(restored[0]['name'], path)
        self.assertIsNone(restored[0]['value'])

    def test_gl_success_records_pending_restart_but_cancel_does_not(self):
        plan = [operation('HKLM', GL, 'DLL', 'example.dll')]
        with patch('gpu_selector.PreviewDialog') as preview:
            preview.return_value.exec.return_value = QDialog.Rejected
            self.window.execute(plan, 'OpenGL')
            self.assertEqual(reboot_status(self.tmp.name)['state'], 'none')
            preview.return_value.exec.return_value = QDialog.Accepted
            self.window.execute(plan, 'OpenGL')
        self.assertEqual(reboot_status(self.tmp.name)['state'], 'pending')

    def test_log_failure_does_not_undo_successful_apply(self):
        with patch('gpu_selector.PreviewDialog') as preview, patch('system_status.write_log', side_effect=OSError('disk full')):
            preview.return_value.exec.return_value = QDialog.Accepted
            self.assertTrue(self.window.execute(self.plan, 'test'))
        self.assertEqual(self.db.read('HKCU', PREF, GLOBAL)[0], 'HighPerfAdapter=TEST;')

    def test_preferences_and_geometry_persist(self):
        self.window.theme_combo.setCurrentIndex(1)
        self.window.font_spin.setValue(12)
        self.window.resize(800, 700)
        self.window.close()
        prefs = load_preferences(self.tmp.name)
        self.assertEqual(prefs['theme'], 'light')
        self.assertEqual(prefs['font_size'], 12)
        self.assertTrue(prefs['geometry'])

    def test_invalid_preferences_have_safe_defaults(self):
        Path(self.tmp.name, 'ui.json').write_text('{broken', encoding='utf-8')
        self.assertEqual(load_preferences(self.tmp.name), {'theme':'dark', 'font_size':10})
        save_preferences(self.tmp.name, {'theme':'other', 'font_size':500})
        self.assertEqual(load_preferences(self.tmp.name)['font_size'], 14)
        self.assertEqual(load_preferences(self.tmp.name)['theme'], 'dark')

    def test_light_theme_replaces_background_without_cascading_and_scales_font(self):
        css = style_for(ui.STYLE, 'light', 12)
        self.assertIn('background: #f3f6fc', css)
        self.assertIn('font-size: 12pt', css)
        self.assertNotIn('background: #101522', css)

    def test_invalid_zero_numeric_global_value_is_not_treated_as_empty(self):
        self.db.write('HKCU', PREF, GLOBAL, 64, [0, 4])
        with self.assertRaises(ValueError):
            dx_target(self.db)

    def test_duplicate_case_insensitive_targets_rejected(self):
        plan = [operation('HKCU', PREF, r'C:\A.exe', 'GpuPreference=1;'),
                operation('HKCU', PREF, r'c:\a.EXE', 'GpuPreference=2;')]
        with self.assertRaisesRegex(ValueError, '重复'):
            validate_operations(plan)

    def test_button_does_not_pass_checked_flag_into_manual_refresh(self):
        from unittest.mock import Mock
        callback = Mock()
        item = ui.button('refresh', callback)
        item.click()
        callback.assert_called_once_with()

    def test_unchanged_gl_in_profile_does_not_require_admin_or_reboot(self):
        unchanged = operation('HKLM', GL, 'DLL', 'same.dll')
        self.db.write(**unchanged)
        app = operation('HKCU', PREF, r'C:\Game.exe', 'GpuPreference=2;')
        with patch('gpu_selector.PreviewDialog') as preview, patch('gpu_selector.admin', return_value=False), patch('system_status.record_gl_change') as reboot:
            preview.return_value.exec.return_value = QDialog.Accepted
            self.assertTrue(self.window.execute([unchanged, app], 'mixed-profile'))
            reboot.assert_not_called()
        snapshot = json.loads(self.window.last_backup.read_text(encoding='utf-8'))
        self.assertEqual(len(snapshot['after']), 1)
        self.assertEqual(snapshot['after'][0]['root'], 'HKCU')

    def test_visible_application_table_refreshes_with_timer(self):
        self.window.tabs.setCurrentIndex(2)
        with patch.object(self.window.application_page, 'refresh', return_value=True) as refresh:
            self.window.refresh(rescan=False)
            refresh.assert_called_once()


if __name__ == '__main__':
    unittest.main()
